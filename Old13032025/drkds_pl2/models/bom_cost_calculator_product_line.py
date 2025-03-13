from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging


class BOMCostCalculatorProductLine(models.Model):
    _name = 'mrp.bom.cost.calculator.product.line'
    _description = 'BOM Cost Calculator Product Line'

    calculator_id = fields.Many2one('mrp.bom.cost.calculator', 'Calculator', required=True)
    product_id = fields.Many2one('product.product', 'Product', required=True)
    product_tmpl_id = fields.Many2one('product.template', related='product_id.product_tmpl_id', 
        string='Product Template', store=True)
    
    is_manufacture = fields.Boolean('Manufacturing Product', default=False)
    bom_id = fields.Many2one('mrp.bom', 'Bill of Materials', 
        domain="[('product_tmpl_id', '=', product_tmpl_id)]")
    
    material_cost = fields.Float('Material Cost', digits='Product Price')
    operation_cost = fields.Float('Operation Cost', digits='Product Price')
    
    jobwork_cost = fields.Float('Job Work Cost', digits='Product Price')
    freight_cost = fields.Float('Freight Cost', digits='Product Price')
    packing_cost = fields.Float('Packing Cost', digits='Product Price')
    cushion = fields.Float('Cushion', digits='Product Price')
    gross_profit_add = fields.Float('Gross Profit Addition', digits='Product Price')
    unit_cost = fields.Float('Cost Per Unit', compute='_compute_unit_cost', store=True)

    
    # Add other_cost computed field
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
        ('applied', 'Applied')
    ], string='Status', default='draft')
    
    @api.depends('total_cost', 'bom_id')
    def _compute_unit_cost(self):
        for record in self:
            if record.bom_id and record.bom_id.product_qty > 0:
                record.unit_cost = record.total_cost / record.bom_id.product_qty
            else:
                record.unit_cost = record.total_cost
            
    @api.depends('jobwork_cost', 'freight_cost', 'packing_cost', 'cushion', 'gross_profit_add')
    def _compute_other_cost(self):
        for record in self:
            record.other_cost = sum([
                record.jobwork_cost or 0.0,
                record.freight_cost or 0.0,
                record.packing_cost or 0.0,
                record.cushion or 0.0,
                record.gross_profit_add or 0.0
            ])

    @api.depends('material_cost', 'operation_cost', 'jobwork_cost', 'freight_cost', 
                 'packing_cost', 'cushion', 'gross_profit_add')
    def _compute_total_cost(self):
        for record in self:
            record.total_cost = sum([
                record.material_cost or 0.0,
                record.operation_cost or 0.0,
                record.jobwork_cost or 0.0,
                record.freight_cost or 0.0,
                record.packing_cost or 0.0,
                record.cushion or 0.0,
                record.gross_profit_add or 0.0
            ])
    
    def action_reset_to_draft(self):
        """Reset the line to draft status to allow modifications"""
        self.ensure_one()
        if self.state != 'applied':
            self.state = 'draft'
        else:
            raise UserError(_("Cannot reset an applied cost calculation. Create a new calculation instead."))
        return True
    
    def action_open_additional_costs(self):
        """Open a wizard to edit additional costs"""
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
        if not self.product_id:
            self.bom_id = False
            return
            
        # Get default BOM if exists
        bom = self.env['mrp.bom']._bom_find(
            products=self.product_id,
            company_id=self.env.company.id,
            picking_type=False
        ).get(self.product_id)
        
        self.is_manufacture = bool(bom)
        self.bom_id = bom.id if bom else False
        
        # Update additional costs from product
        self.jobwork_cost = self.product_id.total_jobwork_cost or 0.0
        self.freight_cost = self.product_id.total_freight_cost or 0.0
        self.packing_cost = self.product_id.total_packing_cost or 0.0
        self.cushion = self.product_id.cushion or 0.0
        self.gross_profit_add = self.product_id.gross_profit_add or 0.0
    
    @api.onchange('product_id', 'is_manufacture')
    def _onchange_product_is_manufacture(self):
        self.bom_id = False
        if self.is_manufacture and self.product_id:
            domain = [('product_tmpl_id', '=', self.product_id.product_tmpl_id.id)]
            default_bom = self.env['mrp.bom'].search(domain, limit=1, order='create_date desc')
            self.bom_id = default_bom