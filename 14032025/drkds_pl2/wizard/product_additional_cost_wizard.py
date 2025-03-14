from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)

class ProductAdditionalCostWizard(models.TransientModel):
    _name = 'product.additional.cost.wizard'
    _description = 'Product Additional Cost Wizard'

    line_id = fields.Many2one(
        'mrp.bom.cost.calculator.product.line', 
        string='Product Line', 
        required=True
    )
    
    product_id = fields.Many2one(
        'product.product', 
        related='line_id.product_id', 
        string='Product', 
        readonly=True
    )
    
    # Cost-related fields
    jobwork_cost = fields.Float(
        'Job Work Cost', 
        digits='Product Price',
        help="Additional job work costs"
    )
    
    freight_cost = fields.Float(
        'Freight Cost', 
        digits='Product Price',
        help="Transportation and shipping costs"
    )
    
    packing_cost = fields.Float(
        'Packing Cost', 
        digits='Product Price',
        help="Packaging and handling costs"
    )
    
    cushion = fields.Float(
        'Cushion', 
        digits='Product Price',
        help="Additional buffer or contingency cost"
    )
    
    gross_profit_add = fields.Float(
        'Gross Profit Addition', 
        digits='Product Price',
        help="Additional margin or profit markup"
    )
    
    # Price Level Fields
    level1Add = fields.Float(
        'Level 1 Addition', 
        digits='Product Price',
        help="Price addition for Level 1"
    )
    
    level2Add = fields.Float(
        'Level 2 Addition', 
        digits='Product Price',
        help="Price addition for Level 2"
    )
    
    level3Add = fields.Float(
        'Level 3 Addition', 
        digits='Product Price',
        help="Price addition for Level 3"
    )
    
    level4Add = fields.Float(
        'Level 4 Addition', 
        digits='Product Price',
        help="Price addition for Level 4"
    )
    
    # Computed Price Levels
    level1price = fields.Float(
        'Level 1 Price', 
        compute='_compute_level_prices', 
        store=True, 
        digits='Product Price'
    )
    
    level2price = fields.Float(
        'Level 2 Price', 
        compute='_compute_level_prices', 
        store=True, 
        digits='Product Price'
    )
    
    level3price = fields.Float(
        'Level 3 Price', 
        compute='_compute_level_prices', 
        store=True, 
        digits='Product Price'
    )
    
    level4price = fields.Float(
        'Level 4 Price', 
        compute='_compute_level_prices', 
        store=True, 
        digits='Product Price'
    )
    
    include_in_pricelist = fields.Boolean(
        'Include in Pricelist', 
        help="Whether this product should be included in price lists"
    )
    
    is_calculated = fields.Boolean(
        'Is Calculated', 
        compute='_compute_is_calculated',
        help="Indicates if the line has been calculated"
    )
    
    @api.depends('line_id.state')
    def _compute_is_calculated(self):
        """Determine calculation state"""
        for record in self:
            record.is_calculated = record.line_id.state != 'draft'
    
    def _get_safe_calculator(self, product_id):
        """
        Safely retrieve the most recent cost calculator
        """
        try:
            calculator = self.env['mrp.bom.cost.calculator'].search([
                ('product_id', '=', product_id),
                ('state', 'in', ['calculated', 'applied'])
            ], limit=1, order='create_date desc')
            
            return calculator
        except Exception as e:
            _logger.error(f"Error retrieving calculator: {str(e)}")
            return None
    
    @api.depends('product_id', 'level1Add', 'level2Add', 'level3Add', 'level4Add')
    def _compute_level_prices(self):
        """Calculate price levels"""
        for record in self:
            if not record.product_id:
                record.level1price = record.level2price = record.level3price = record.level4price = 0.0
                continue
            
            calculator = self._get_safe_calculator(record.product_id.id)
            
            if calculator and hasattr(calculator, 'unit_cost'):
                base_cost = calculator.unit_cost
                record.level1price = base_cost + record.level1Add
                record.level2price = record.level1price + record.level2Add
                record.level3price = record.level2price + record.level3Add
                record.level4price = record.level3price + record.level4Add
            else:
                record.level1price = record.level2price = record.level3price = record.level4price = 0.0
    
    @api.model
    def default_get(self, fields_list):
        """Load values from the selected line"""
        res = super().default_get(fields_list)
        
        if self._context.get('active_id'):
            line = self.env['mrp.bom.cost.calculator.product.line'].browse(self._context.get('active_id'))
            
            # Check if line is already calculated
            if line.state != 'draft':
                res.update({
                    'line_id': line.id,
                    'jobwork_cost': line.jobwork_cost,
                    'freight_cost': line.freight_cost,
                    'packing_cost': line.packing_cost,
                    'cushion': line.cushion,
                    'gross_profit_add': line.gross_profit_add,
                })
            else:
                # Prefill from product if in draft state
                res.update({
                    'line_id': line.id,
                    'jobwork_cost': line.jobwork_cost or line.product_id.total_jobwork_cost or 0.0,
                    'freight_cost': line.freight_cost or line.product_id.total_freight_cost or 0.0,
                    'packing_cost': line.packing_cost or line.product_id.total_packing_cost or 0.0,
                    'cushion': line.cushion or line.product_id.cushion or 0.0,
                    'gross_profit_add': line.gross_profit_add or line.product_id.gross_profit_add or 0.0,
                })
            
            # Load level additions from product template
            product_tmpl = line.product_id.product_tmpl_id
            res.update({
                'level1Add': getattr(product_tmpl, 'level1Add', 0.0),
                'level2Add': getattr(product_tmpl, 'level2Add', 0.0),
                'level3Add': getattr(product_tmpl, 'level3Add', 0.0),
                'level4Add': getattr(product_tmpl, 'level4Add', 0.0),
                'include_in_pricelist': getattr(product_tmpl, 'include_in_pricelist', False)
            })
        
        return res
    
    def action_save_additional_costs(self):
        """Update the product line with new values"""
        self.ensure_one()
        
        # Check if already calculated
        if self.line_id.state != 'draft':
            raise UserError(_("Cannot modify costs after calculation. Reset to draft first."))
        
        # Update values on the calculator line
        values = {
            'jobwork_cost': self.jobwork_cost,
            'freight_cost': self.freight_cost,
            'packing_cost': self.packing_cost,
            'cushion': self.cushion,
            'gross_profit_add': self.gross_profit_add,
        }
        
        # Update line with values
        self.line_id.write(values)
        
        # Calculate total cost
        new_total = (
            self.line_id.material_cost + 
            self.line_id.operation_cost +
            self.jobwork_cost +
            self.freight_cost +
            self.packing_cost +
            self.cushion +
            self.gross_profit_add
        )
        
        # Calculate other cost
        other_cost = (
            self.jobwork_cost +
            self.freight_cost +
            self.packing_cost +
            self.cushion +
            self.gross_profit_add
        )
        
        # Update total cost and other cost
        self.line_id.write({
            'total_cost': new_total,
            'other_cost': other_cost
        })
        
        return {'type': 'ir.actions.act_window_close'}
    
    def action_save_and_update_product(self):
        """Update the product line and save values to the product model"""
        self.ensure_one()
        
        # Check if already calculated
        if self.line_id.state != 'draft':
            raise UserError(_("Cannot modify costs after calculation. Reset to draft first."))
        
        # First update the line
        self.action_save_additional_costs()
        
        # Then update the product
        if self.product_id:
            # Main cost values
            values = {
                'total_jobwork_cost': self.jobwork_cost,
                'total_freight_cost': self.freight_cost,
                'total_packing_cost': self.packing_cost,
                'cushion': self.cushion,
                'gross_profit_add': self.gross_profit_add,
            }
            
            # Save main values
            self.product_id.write(values)
            
            # Save level prices to product template
            template = self.product_id.product_tmpl_id
            template_values = {
                'level1Add': self.level1Add,
                'level2Add': self.level2Add,
                'level3Add': self.level3Add,
                'level4Add': self.level4Add,
                'include_in_pricelist': self.include_in_pricelist
            }
            
            template.write(template_values)
        
        return {'type': 'ir.actions.act_window_close'}