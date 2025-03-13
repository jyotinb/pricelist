from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class BOMCostCalculator(models.Model):
    _name = 'mrp.bom.cost.calculator'
    _description = 'BOM Cost Calculator'
    _order = 'id desc'

    name = fields.Char('Reference', default='New', readonly=True)
    date = fields.Datetime('Calculation Date', default=fields.Datetime.now, required=True)
    
    product_id = fields.Many2one('product.product', 'Product', required=False)
    product_tmpl_id = fields.Many2one('product.template', related='product_id.product_tmpl_id', 
        string='Product Template', store=True)
    
    bom_id = fields.Many2one('mrp.bom', 'Bill of Materials', 
        domain="[('product_tmpl_id', '=', product_tmpl_id)]", 
        required=False)
    
    include_operations = fields.Boolean('Include Operations Cost', default=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('calculated', 'Calculated'),
        ('applied', 'Applied')
    ], string='Status', default='draft')
    
    total_material_cost = fields.Float('Total Material Cost', readonly=True)
    total_operation_cost = fields.Float('Total Operation Cost', readonly=True)
    
    total_jobwork_cost = fields.Float('Total Job Work Cost', readonly=True)
    total_freight_cost = fields.Float('Total Freight Cost', readonly=True)
    total_packing_cost = fields.Float('Total Packing Cost', readonly=True)
    cushion = fields.Float('Cushion', readonly=True)
    gross_profit_add = fields.Float('Gross Profit Addition', readonly=True)
    
    
    total_cost = fields.Float('Total Cost', readonly=True)
    cost_details_ids = fields.One2many('mrp.bom.cost.calculator.line', 'calculator_id', 'Cost Details')
    
    is_multi_product = fields.Boolean('Multiple Products', default=False)
    product_line_ids = fields.One2many('mrp.bom.cost.calculator.product.line', 'calculator_id', 'Products to Calculate')
    other_cost = fields.Float(
        string='Other Cost',
        readonly=True ,
        store=True
    )
    unit_cost = fields.Float('Cost Per Unit', compute='_compute_unit_cost', store=True)

    @api.depends('total_cost', 'bom_id')
    def _compute_unit_cost(self):
        for record in self:
            if record.bom_id and record.bom_id.product_qty > 0:
                record.unit_cost = record.total_cost / record.bom_id.product_qty
            else:
                record.unit_cost = record.total_cost
    
    @api.constrains('product_id', 'bom_id', 'is_multi_product')
    def _check_required_fields(self):
        for record in self:
            if not record.is_multi_product:
                if not record.product_id:
                    raise ValidationError(_("Product is required when not in multi-product mode."))
                if not record.bom_id:
                    raise ValidationError(_("Bill of Materials is required when not in multi-product mode."))
            

    

    def add_products_wizard(self):
        """Open wizard to select products"""
        # Try to find the view safely
        try:
            # First try the original ID
            view_id = self.env.ref('drkds_pl2.view_product_selection_wizard_form')
        except ValueError:
            # If that fails, try with a different module name
            try:
                view_id = self.env.ref('drkds_pl_product.view_product_selection_wizard_form')
            except ValueError:
                # If still not found, don't specify a view ID - Odoo will use the default
                view_id = False
                
        return {
            'name': _('Select Products'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'product.selection.wizard',
            'view_id': view_id.id if view_id else False,
            'target': 'new',
            'context': {
                'default_calculator_id': self.id,
            },
        }
    
    
    def action_open_product_selection(self):
        """Open a wizard to select products"""
        return {
            'name': 'Select Products',
            'type': 'ir.actions.act_window',
            'res_model': 'product.product',
            'view_mode': 'tree',
            'view_id': False,
            'domain': [('sale_ok', '=', True)],
            'context': {
                'default_calculator_id': self.id,
            },
            'target': 'new',
            'multi_select': True,
        }

    def add_product_lines(self, product_ids):
        """Add multiple product lines"""
        for product_id in product_ids:
            # Find default BOM if exists
            bom = self.env['mrp.bom']._bom_find(
                product_id=product_id,
                company_id=self.env.company.id
            )[product_id]
            
            self.env['mrp.bom.cost.calculator.product.line'].create({
                'calculator_id': self.id,
                'product_id': product_id,
                'is_manufacture': bool(bom),
                'bom_id': bom.id if bom else False,
                'state': 'draft'
            })
    
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        if not self.product_id:
            self.bom_id = False
            return {
                'domain': {'bom_id': [('id', '=', False)]},  # Empty dropdown
                'value': {'bom_id': False}
            }

        # Get product template ID
        product_tmpl_id = self.product_id.product_tmpl_id.id

        # Set domain to only show BOMs related to the selected product template
        domain = [('product_tmpl_id', '=', product_tmpl_id)]
        default_bom = self.env['mrp.bom'].search(domain, limit=1, order='create_date desc')

        # Get additional costs from product
        self.total_jobwork_cost = self.product_id.total_jobwork_cost or 0.0
        self.total_freight_cost = self.product_id.total_freight_cost or 0.0
        self.total_packing_cost = self.product_id.total_packing_cost or 0.0
        self.cushion = self.product_id.cushion or 0.0
        self.gross_profit_add = self.product_id.gross_profit_add or 0.0

        return {
            'domain': {'bom_id': domain},  # Restrict dropdown to relevant BOMs
            'value': {'bom_id': default_bom.id if default_bom else False}
        }
        
        
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('mrp.bom.cost.calculator') or 'New'
        return super().create(vals_list)

   

    def _calculate_bom_cost(self, bom, processed_boms=None, create_lines=True, level=0, product=None):
        """
        Calculate BOM cost where:
        - Material costs are only included for raw materials (no BOM)
        - Components from BOMs only consider quantity ratios
        - Handles unit costs from pre-calculated components
        """
        if not bom:
            return 0, 0, 0
            
        # Use provided product or fall back to the one on the record
        product_to_use = product or self.product_id
                
        if processed_boms is None:
            processed_boms = set()
                
        if bom.id in processed_boms:
            return 0, 0, 0
        processed_boms.add(bom.id)
            
        material_total = 0
        operation_total = 0
        total_duration = 0

        # Operation costs
        if self.include_operations:
            for operation in bom.operation_ids:
                if operation._skip_operation_line(product_to_use):
                    continue
                        
                duration_expected = (
                    operation.time_cycle or 
                    operation.time_cycle_manual or 
                    operation.duration_expected or 
                    0.0
                )
                
                total_duration += duration_expected
                
                cost_per_minute = operation._total_cost_per_hour() / 60
                operation_cost = duration_expected * cost_per_minute
                    
                if create_lines:
                    self.env['mrp.bom.cost.calculator.line'].create({
                        'calculator_id': self.id,
                        'name': f"{bom.product_tmpl_id.display_name} - {operation.workcenter_id.name} ({operation.name or 'Operation'})",
                        'cost_type': 'operation',
                        'operation_id': operation.id,
                        'duration': duration_expected,
                        'unit_cost': operation._total_cost_per_hour(),
                        'cost': operation_cost,
                        'bom_level': level,
                        'bom_qty': bom.product_qty,
                    })

                operation_total += operation_cost

        # Material costs
        for line in bom.bom_line_ids:
            if line._skip_bom_line(product_to_use):
                continue

            line_qty = line.product_uom_id._compute_quantity(
                line.product_qty, line.product_id.uom_id)

            child_bom = self.env['mrp.bom']._bom_find(
                products=line.product_id,
                company_id=bom.company_id.id,
                picking_type=False
            ).get(line.product_id)

            if child_bom:
                # Look for an existing calculator with unit cost for this component
                child_calculator = self.env['mrp.bom.cost.calculator'].search([
                    ('product_id', '=', line.product_id.id),
                    ('state', '=', 'calculated')
                ], limit=1, order='create_date desc')
                
                # Check if we can use the existing calculator
                if child_calculator:
                    # Calculate unit cost based on BOM quantity if available
                    if child_calculator.bom_id and child_calculator.bom_id.product_qty > 0:
                        unit_cost = child_calculator.total_cost / child_calculator.bom_id.product_qty
                    else:
                        unit_cost = child_calculator.total_cost
                    
                    # Handle UoM conversions if needed
                    if child_calculator.bom_id and child_calculator.bom_id.product_uom_id.id != line.product_uom_id.id:
                        # Convert the unit cost to the line's UoM
                        converted_cost = child_calculator.bom_id.product_uom_id._compute_price(
                            unit_cost, line.product_uom_id)
                        component_cost = converted_cost * line.product_qty
                    else:
                        component_cost = unit_cost * line_qty
                        
                    material_total += component_cost
                    
                    if create_lines:
                        self.env['mrp.bom.cost.calculator.line'].create({
                            'calculator_id': self.id,
                            'name': f"{line.product_id.display_name} (Component with Pre-calculated Cost)",
                            'cost_type': 'material',
                            'product_id': line.product_id.id,
                            'quantity': line_qty,
                            'unit_cost': unit_cost,
                            'cost': component_cost,
                            'bom_level': level,
                            'bom_qty': bom.product_qty,
                        })
                else:
                    # For components with BOMs, we only pass through their costs 
                    # without adding new material costs
                    child_material, child_operation, child_duration = self._calculate_bom_cost(
                        child_bom, 
                        processed_boms.copy(),
                        create_lines=True,
                        level=level + 1,
                        product=line.product_id
                    )
                    
                    # Add child costs considering the quantity ratio
                    # We need to ensure UoM compatibility
                    if child_bom.product_uom_id.id != line.product_uom_id.id:
                        # Convert child BOM quantity to line's UoM
                        child_bom_qty_in_line_uom = child_bom.product_uom_id._compute_quantity(
                            child_bom.product_qty, line.product_uom_id)
                        qty_ratio = line.product_qty / (child_bom_qty_in_line_uom or 1.0)
                    else:
                        qty_ratio = line.product_qty / (child_bom.product_qty or 1.0)
                    
                    material_total += child_material * qty_ratio
                    operation_total += child_operation * qty_ratio
                    total_duration += child_duration * qty_ratio
                    
                    if create_lines:
                        # Calculate unit cost based on BOM quantity
                        unit_cost = child_material / (child_bom.product_qty or 1.0)
                        
                        # If UoMs differ, convert the unit cost
                        if child_bom.product_uom_id.id != line.product_uom_id.id:
                            unit_cost = child_bom.product_uom_id._compute_price(
                                unit_cost, line.product_uom_id)
                        
                        self.env['mrp.bom.cost.calculator.line'].create({
                            'calculator_id': self.id,
                            'name': f"{line.product_id.display_name} (Component from BOM)",
                            'cost_type': 'material',
                            'product_id': line.product_id.id,
                            'quantity': line_qty,
                            'unit_cost': unit_cost,
                            'cost': child_material * qty_ratio,
                            'bom_level': level,
                            'bom_qty': bom.product_qty,
                        })
                
            else:
                # Only add material cost for raw materials (no BOM)
                component_cost = line.product_id.standard_price * line_qty
                material_total += component_cost

                if create_lines:
                    self.env['mrp.bom.cost.calculator.line'].create({
                        'calculator_id': self.id,
                        'name': f"{line.product_id.display_name} (Raw Material)",
                        'cost_type': 'material',
                        'product_id': line.product_id.id,
                        'quantity': line_qty,
                        'unit_cost': line.product_id.standard_price,
                        'cost': component_cost,
                        'bom_level': level,
                        'bom_qty': bom.product_qty,
                    })

        return material_total, operation_total, total_duration
        
    def action_calculate_cost(self):
        """Calculate cost for single product mode"""
        self.ensure_one()
        if not self.bom_id:
            raise UserError(_('Please select a BOM first.'))
                
        self.cost_details_ids.unlink()
        material_cost, operation_cost, total_duration = self._calculate_bom_cost(self.bom_id, level=0, product=None)
            
        self.total_material_cost = material_cost
        self.total_operation_cost = operation_cost
        self.total_jobwork_cost = self.product_id.total_jobwork_cost or 0.0
        self.total_freight_cost = self.product_id.total_freight_cost or 0.0
        self.total_packing_cost = self.product_id.total_packing_cost or 0.0
        self.cushion = self.product_id.cushion or 0.0
        self.gross_profit_add = self.product_id.gross_profit_add or 0.0
        
        
        per_unit_other_cost = (
            self.total_jobwork_cost + 
            self.total_freight_cost + 
            self.total_packing_cost + 
            self.cushion + 
            self.gross_profit_add
        )
        
        # Scale other costs by BOM quantity for total batch cost
        bom_qty = self.bom_id.product_qty or 1.0
        self.other_cost = per_unit_other_cost * bom_qty
        
        
        # Calculate total cost
        self.total_cost = (
            material_cost + 
            operation_cost + 
            self.other_cost
        )
        
        self.state = 'calculated'
        return True
        
    

    def action_apply_cost(self):
        """Apply calculated cost to the product's standard price"""
        self.ensure_one()
        if self.state != 'calculated':
            raise UserError(_('Please calculate the costs first.'))

        if not self.product_id:
            raise UserError(_('No product selected.'))

        # Always use unit cost
        if self.bom_id:
            # Check if UoM is consistent with product UoM
            if self.bom_id.product_uom_id.id != self.product_id.uom_id.id:
                # Convert cost to product's UoM
                converted_cost = self.bom_id.product_uom_id._compute_price(
                    self.unit_cost, self.product_id.uom_id)
                self.product_id.standard_price = converted_cost
            else:
                self.product_id.standard_price = self.unit_cost
        else:
            self.product_id.standard_price = self.total_cost
            
        self.state = 'applied'
        return True

    def action_calculate_all_costs(self):
        """Calculate costs for all selected products"""
        self.ensure_one()
        if not self.product_line_ids:
            raise UserError(_('Please select at least one product.'))

        # Initialize totals for the main calculator
        total_material_cost = 0.0
        total_operation_cost = 0.0
        total_jobwork_cost = 0.0
        total_freight_cost = 0.0
        total_packing_cost = 0.0
        total_cushion = 0.0
        total_gross_profit = 0.0
        total_other_cost = 0.0  

        for line in self.product_line_ids:
            if not line.is_manufacture or not line.bom_id:
                line.write({
                    'state': 'calculated',
                    # You might want to set default values or zeros for costs
                    'material_cost': line.product_id.standard_price,
                    # ...other fields as needed
                })
                continue
                
             # Temporarily store the current product_id
            original_product_id = self.product_id
            
            # Set the product_id to the line's product for the calculation
            self.product_id = line.product_id
            
            try:
                material_cost, operation_cost, total_duration = self._calculate_bom_cost(
                    line.bom_id, 
                    level=0,
                    create_lines=False
                )

                material_cost, operation_cost, total_duration = self._calculate_bom_cost(
                    line.bom_id, 
                    level=0,
                    create_lines=False,
                    product=line.product_id 
                )
                
                # Get additional costs from product
                jobwork_cost = line.product_id.total_jobwork_cost or 0.0
                freight_cost = line.product_id.total_freight_cost or 0.0
                packing_cost = line.product_id.total_packing_cost or 0.0
                cushion_value = line.product_id.cushion or 0.0
                gross_profit = line.product_id.gross_profit_add or 0.0
                
                # Calculate the per-unit other cost
                per_unit_other_cost = (
                    jobwork_cost + 
                    freight_cost + 
                    packing_cost + 
                    cushion_value + 
                    gross_profit
                )
                
                # Scale by BOM quantity
                bom_qty = line.bom_id.product_qty or 1.0
                other_cost = per_unit_other_cost * bom_qty
                    
                # Update product line
                line.write({
                    'material_cost': material_cost,
                    'operation_cost': operation_cost,
                    'jobwork_cost': jobwork_cost * bom_qty,  # Scale by BOM quantity
                    'freight_cost': freight_cost * bom_qty,  # Scale by BOM quantity
                    'packing_cost': packing_cost * bom_qty,  # Scale by BOM quantity
                    'cushion': cushion_value * bom_qty,      # Scale by BOM quantity
                    'gross_profit_add': gross_profit * bom_qty,  # Scale by BOM quantity
                    'other_cost': other_cost,
                    'state': 'calculated'
                })
                
                # Add to calculator totals
                total_material_cost += material_cost
                total_operation_cost += operation_cost
                total_other_cost += other_cost
                
            finally:
                # Restore the original product_id
                self.product_id = original_product_id    
            
            
            
            
            
        # Update calculator with totals
        self.write({
            'total_material_cost': total_material_cost,
            'total_operation_cost': total_operation_cost,
            'total_jobwork_cost': sum(line.jobwork_cost for line in self.product_line_ids),
            'total_freight_cost': sum(line.freight_cost for line in self.product_line_ids),
            'total_packing_cost': sum(line.packing_cost for line in self.product_line_ids),
            'cushion': sum(line.cushion for line in self.product_line_ids),
            'gross_profit_add': sum(line.gross_profit_add for line in self.product_line_ids),
            'other_cost': total_other_cost,
            'total_cost': (
                total_material_cost +
                total_operation_cost +
                total_other_cost
            ),
            'state': 'calculated'
        })
        
        return True

    def action_apply_all_costs(self):
        """Apply calculated costs to all products"""
        self.ensure_one()
        if self.state != 'calculated':
            raise UserError(_('Please calculate the costs first.'))

        for line in self.product_line_ids:
            if line.state != 'calculated' or not line.is_manufacture:
                continue
                
            line.product_id.standard_price = line.total_cost
            line.state = 'applied'

        self.state = 'applied'
        return True
        
    def add_product_line(self):
        """Add a new product line"""
        self.ensure_one()
        self.write({
            'product_line_ids': [(0, 0, {
                'state': 'draft'
            })]
        })
        return True
        
        
    # Add this method to your mrp.bom.cost.calculator model

    def action_open_product_report_wizard(self):
        """
        Open the Product Three Column Report wizard
        """
        self.ensure_one()
        
        # Prepare context and wizard values
        ctx = dict(self.env.context)
        
        # Try to find a default customer to use
        default_customer = False
        
        # Try to get customer from recent sales orders if any
        if not default_customer:
            sales = self.env['sale.order'].search(
                [('state', 'in', ['sale', 'done'])], 
                order='date_order desc', 
                limit=1
            )
            if sales and sales.partner_id:
                default_customer = sales.partner_id.id
        
        # If still no customer, try to get the first customer in the system
        if not default_customer:
            partner = self.env['res.partner'].search(
                [('customer_rank', '>', 0)], 
                limit=1
            )
            if partner:
                default_customer = partner.id
        
        # Create wizard
        wizard = self.env['drkds_pl2.product_three_column_wizard'].create({
            'doc_id': self.id,
            'customer_id': default_customer,
        })
        
        # Open wizard
        return {
            'name': _('Product Three Column Report'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'drkds_pl2.product_three_column_wizard',
            'res_id': wizard.id,
            'target': 'new',
            'context': ctx,
        }
        
    
class BOMCostCalculatorLine(models.Model):
    _name = 'mrp.bom.cost.calculator.line'
    _description = 'BOM Cost Calculator Line'

    calculator_id = fields.Many2one('mrp.bom.cost.calculator', 'Calculator', required=True)
    name = fields.Char('Description', required=True)
    cost_type = fields.Selection([
        ('material', 'Material'),
        ('operation', 'Operation')
    ], string='Cost Type', required=True)
    product_id = fields.Many2one('product.product', 'Component')
    operation_id = fields.Many2one('mrp.routing.workcenter', 'Operation')
    quantity = fields.Float('Quantity', digits='Product Unit of Measure')
    duration = fields.Float('Duration (minutes)')
    unit_cost = fields.Float('Unit Cost', digits='Product Price')
    cost = fields.Float('Cost', digits='Product Price')
    bom_level = fields.Integer('BOM Level', default=0)
    bom_qty = fields.Float('BOM Production Qty', digits='Product Unit of Measure')  #
    
    

    
    
    
class ProductSelectionWizard(models.TransientModel):
    _name = 'product.selection.wizard'
    _description = 'Product Selection Wizard'

    calculator_id = fields.Many2one('mrp.bom.cost.calculator', string='Calculator')
    product_ids = fields.Many2many('product.product', string='Products', 
        domain=[('sale_ok', '=', True)])

    def action_add_products(self):
        self.ensure_one()
        for product in self.product_ids:
            # Find default BOM using the new method signature
            bom = self.env['mrp.bom']._bom_find(
                products=product,
                company_id=self.env.company.id,
                picking_type=False
            )
            # Get the BOM for this specific product
            product_bom = bom.get(product)
            
            self.env['mrp.bom.cost.calculator.product.line'].create({
                'calculator_id': self.calculator_id.id,
                'product_id': product.id,
                'is_manufacture': bool(product_bom),
                'bom_id': product_bom.id if product_bom else False,
                'state': 'draft'
            })
        return {'type': 'ir.actions.act_window_close'}