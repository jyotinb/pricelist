from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class BOMCostCalculatorProductLine(models.Model):
    _name = 'mrp.bom.cost.calculator.product.line'
    _description = 'BOM Cost Calculator Product Line'
    _order = 'id asc'  # Order by ID to maintain creation order

    calculator_id = fields.Many2one('mrp.bom.cost.calculator', 'Calculator', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', 'Product', required=True, index=True)
    product_tmpl_id = fields.Many2one('product.template', related='product_id.product_tmpl_id', 
        string='Product Template', store=True, index=True)
    
    is_manufacture = fields.Boolean('Manufacturing Product', default=False)
    bom_id = fields.Many2one('mrp.bom', 'Bill of Materials', 
        domain="[('product_tmpl_id', '=', product_tmpl_id)]")
    
    # Cost fields
    material_cost = fields.Float('Material Cost', digits='Product Price')
    operation_cost = fields.Float('Operation Cost', digits='Product Price')
    
    # Additional costs - apply to both manufactured and non-manufactured items
    jobwork_cost = fields.Float('Job Work Cost', digits='Product Price')
    freight_cost = fields.Float('Freight Cost', digits='Product Price')
    packing_cost = fields.Float('Packing Cost', digits='Product Price')
    cushion = fields.Float('Cushion', digits='Product Price')
    gross_profit_add = fields.Float('Gross Profit Addition', digits='Product Price')
    unit_cost = fields.Float('Cost Per Unit', compute='_compute_unit_cost', store=True)
    
    # Base cost for non-manufactured items
    base_cost = fields.Float('Base Cost', digits='Product Price', 
                            help="Base cost for non-manufactured items, equivalent to the product's standard price")
    
    # Calculated fields with caching
    other_cost = fields.Float(
        string='Other Cost',
        compute='_compute_other_cost',
        store=True,
        digits='Product Price'
    )
    
    total_cost = fields.Float(
        string='Total Cost',
        compute='_compute_total_cost',
        store=True,
        digits='Product Price'
    )
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('calculated', 'Calculated'),
    ], string='Status', default='draft')
    
    _sql_constraints = [
        ('product_calculator_uniq', 'unique (calculator_id, product_id)', 
         'A product can only appear once in a cost calculator!'),
    ]
    
    @api.depends('total_cost', 'bom_id')
    def _compute_unit_cost(self):
        """
        Compute the unit cost by dividing the total cost by the BOM's output quantity.
        If no BOM is defined or the BOM quantity is zero, the unit cost equals the total cost.
        For non-manufactured items, the unit cost is simply the total cost.
        """
        for record in self:
            if record.is_manufacture and record.bom_id and record.bom_id.product_qty > 0:
                record.unit_cost = record.total_cost / record.bom_id.product_qty
            else:
                record.unit_cost = record.total_cost
            
    @api.depends('jobwork_cost', 'freight_cost', 'packing_cost', 'cushion', 'gross_profit_add')
    def _compute_other_cost(self):
        """
        Compute the total of all additional costs (jobwork, freight, packing, cushion, gross profit).
        This applies to both manufactured and non-manufactured items.
        """
        for record in self:
            record.other_cost = sum([
                record.jobwork_cost or 0.0,
                record.freight_cost or 0.0,
                record.packing_cost or 0.0,
                record.cushion or 0.0,
                record.gross_profit_add or 0.0
            ])

    @api.depends('material_cost', 'operation_cost', 'base_cost', 'other_cost', 'is_manufacture')
    def _compute_total_cost(self):
        """
        Compute the total cost differently based on whether the item is manufactured:
        - For manufactured items: material_cost + operation_cost + other_cost
        - For non-manufactured items: base_cost + other_cost
        """
        for record in self:
            if record.is_manufacture:
                # Manufactured items: use material and operation costs
                record.total_cost = (record.material_cost or 0.0) + (record.operation_cost or 0.0) + (record.other_cost or 0.0)
            else:
                # Non-manufactured items: use base cost instead of material+operation
                record.total_cost = (record.base_cost or 0.0) + (record.other_cost or 0.0)
    
    def action_reset_to_draft(self):
        """
        Reset the line to draft status to allow modifications.
        This can only be done if the line hasn't been calculated yet.
        """
        self.ensure_one()
        if self.state != 'calculated':
            self.state = 'draft'
        else:
            # Keep state if already calculated
            _logger.info("Cannot reset a calculated cost line: %s (Product: %s)",
                         self.id, self.product_id.display_name)
        return True
    
    def action_open_additional_costs(self):
        """
        Open a wizard to edit or view additional costs.
        View-only mode is enforced for lines that are not in draft state.
        """
        self.ensure_one()
        
        # If state is not draft, we're just viewing the costs
        view_mode = 'readonly' if self.state != 'draft' else 'edit'
        
        # Try to find the view with error handling
        try:
            # Try with the original module name
            view_id = self.env.ref('drkds_pl2.view_product_additional_cost_wizard_form')
        except ValueError:
            try:
                # Try with the alternative module name
                view_id = self.env.ref('drkds_pl_product.view_product_additional_cost_wizard_form')
            except ValueError:
                # If still not found, let Odoo use the default view
                view_id = False
                _logger.warning("Could not find view_product_additional_cost_wizard_form")
        
        action_title = _('Edit Additional Costs') if self.state == 'draft' else _('View Additional Costs')
        
        return {
            'name': action_title,
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'product.additional.cost.wizard',
            'view_id': view_id.id if view_id else False,
            'target': 'new',
            'context': {
                'active_id': self.id,
                'form_view_initial_mode': view_mode,
            },
        }
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        """
        When the product changes:
        1. Find and set the default BOM if available
        2. Update the manufacturing flag
        3. Load additional costs from the product
        4. For non-manufactured items, set base cost from product's standard price
        """
        if not self.product_id:
            self.bom_id = False
            self.base_cost = 0.0
            return
            
        # Get default BOM if exists
        bom = self._find_product_bom(self.product_id)
        
        self.is_manufacture = bool(bom)
        self.bom_id = bom.id if bom else False
        
        # Update additional costs from product only if they exist
        self._load_product_costs()
        
        # For non-manufactured items, set the base cost from standard price
        if not self.is_manufacture:
            self.base_cost = self.product_id.standard_price or 0.0
            self.material_cost = 0.0
            self.operation_cost = 0.0
    
    def _find_product_bom(self, product):
        """
        Find the default BOM for a product.
        Returns the BOM record or False if not found.
        """
        if not product:
            return False
            
        bom = self.env['mrp.bom']._bom_find(
            products=product,
            company_id=self.env.company.id,
            picking_type=False
        ).get(product)
        
        return bom
    
    def _load_product_costs(self):
        """
        Load additional cost fields from the product.
        Only sets values if the fields exist on the product model.
        """
        if not self.product_id:
            return
            
        # Check if these fields exist on the product model
        cost_fields = [
            'total_jobwork_cost', 'total_freight_cost', 'total_packing_cost',
            'cushion', 'gross_profit_add'
        ]
        
        # Get fields that exist on the product model
        existing_fields = [f for f in cost_fields if f in self.product_id._fields]
        
        # Only set values for fields that exist
        if 'total_jobwork_cost' in existing_fields:
            self.jobwork_cost = self.product_id.total_jobwork_cost or 0.0
        if 'total_freight_cost' in existing_fields:
            self.freight_cost = self.product_id.total_freight_cost or 0.0
        if 'total_packing_cost' in existing_fields:
            self.packing_cost = self.product_id.total_packing_cost or 0.0
        if 'cushion' in existing_fields:
            self.cushion = self.product_id.cushion or 0.0
        if 'gross_profit_add' in existing_fields:
            self.gross_profit_add = self.product_id.gross_profit_add or 0.0
    
    @api.onchange('product_id', 'is_manufacture')
    def _onchange_product_is_manufacture(self):
        """
        When the product or manufacturing flag changes:
        1. Clear the BOM if manufacturing flag is off
        2. Find and set the default BOM if manufacturing flag is on
        3. Handle cost fields appropriately based on manufacturing status
        """
        self.bom_id = False
        
        if self.is_manufacture and self.product_id:
            # For manufactured items
            domain = [('product_tmpl_id', '=', self.product_id.product_tmpl_id.id)]
            default_bom = self.env['mrp.bom'].search(domain, limit=1, order='create_date desc')
            self.bom_id = default_bom
            # Clear base cost as it's not used for manufactured items
            self.base_cost = 0.0
        elif self.product_id:
            # For non-manufactured items
            self.base_cost = self.product_id.standard_price or 0.0
            # Clear manufacturing-related costs
            self.material_cost = 0.0
            self.operation_cost = 0.0
    
    @api.model
    def calculate_non_manufactured_costs(self, calculator_id):
        """
        Handle cost calculation for non-manufactured items in bulk.
        Called from the main calculator to process all non-manufactured lines.
        """
        lines = self.search([
            ('calculator_id', '=', calculator_id),
            ('is_manufacture', '=', False),
            ('state', '=', 'draft')
        ])
        
        for line in lines:
            # Set the base cost from standard price if not already set
            if not line.base_cost and line.product_id:
                line.base_cost = line.product_id.standard_price or 0.0
            
            # Ensure manufacturing costs are zero
            line.material_cost = 0.0
            line.operation_cost = 0.0
            
            # Mark as calculated
            line.state = 'calculated'
        
        return True