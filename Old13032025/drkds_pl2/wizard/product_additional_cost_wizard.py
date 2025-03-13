from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ProductAdditionalCostWizard(models.TransientModel):
    _name = 'product.additional.cost.wizard'
    _description = 'Product Additional Cost Wizard'

    line_id = fields.Many2one('mrp.bom.cost.calculator.product.line', string='Product Line', required=True)
    product_id = fields.Many2one('product.product', related='line_id.product_id', string='Product', readonly=True)
    jobwork_cost = fields.Float('Job Work Cost', digits='Product Price')
    freight_cost = fields.Float('Freight Cost', digits='Product Price')
    packing_cost = fields.Float('Packing Cost', digits='Product Price')
    cushion = fields.Float('Cushion', digits='Product Price')
    gross_profit_add = fields.Float('Gross Profit Addition', digits='Product Price')
    level1Add = fields.Float('Level 1 Addition', digits='Product Price')
    level2Add = fields.Float('Level 2 Addition', digits='Product Price')
    level3Add = fields.Float('Level 3 Addition', digits='Product Price')
    level4Add = fields.Float('Level 4 Addition', digits='Product Price')
    level1price = fields.Float('Level 1 Price', digits='Product Price', compute='_compute_level_prices', readonly=True)
    level2price = fields.Float('Level 2 Price', digits='Product Price', compute='_compute_level_prices', readonly=True)
    level3price = fields.Float('Level 3 Price', digits='Product Price', compute='_compute_level_prices', readonly=True)
    level4price = fields.Float('Level 4 Price', digits='Product Price', compute='_compute_level_prices', readonly=True)
    include_in_pricelist = fields.Boolean('Include in Pricelist')
    is_calculated = fields.Boolean('Is Calculated', compute='_compute_is_calculated')
    
    def _get_calculator(self, product_id):
        """Safely get the calculator model and search for a calculator"""
        try:
            # Try to get the model - this will only work if it's loaded
            model = self.env.registry.get('mrp.bom.cost.calculator')
            if not model:
                return None
                
            # Now use the model to search for calculators
            calculator = self.env['mrp.bom.cost.calculator'].search([
                ('product_id', '=', product_id),
                ('state', 'in', ['calculated', 'applied'])
            ], limit=1, order='date desc')
            
            return calculator
        except Exception:
            return None
    
    @api.depends('product_id', 'level1Add', 'level2Add', 'level3Add', 'level4Add')
    def _compute_level_prices(self):
        for record in self:
            if not record.product_id:
                record.level1price = 0.0
                record.level2price = 0.0
                record.level3price = 0.0
                record.level4price = 0.0
                continue
                
            calculator = self._get_calculator(record.product_id.id)
            
            # If a calculator is found, use its unit_cost; otherwise, set prices to 0
            if calculator and hasattr(calculator, 'unit_cost'):
                base_cost = calculator.unit_cost
                record.level1price = base_cost + record.level1Add
                record.level2price = record.level1price + record.level2Add
                record.level3price = record.level2price + record.level3Add
                record.level4price = record.level3price + record.level4Add
            else:
                record.level1price = 0.0
                record.level2price = 0.0
                record.level3price = 0.0
                record.level4price = 0.0
    
    @api.depends('line_id.state')
    def _compute_is_calculated(self):
        for record in self:
            record.is_calculated = record.line_id.state != 'draft'

    @api.model
    def default_get(self, fields_list):
        """Load the values from the selected line"""
        res = super().default_get(fields_list)
        
        if self._context.get('active_id'):
            line = self.env['mrp.bom.cost.calculator.product.line'].browse(self._context.get('active_id'))
            
            # Check if the line is already calculated
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
                # Only if in draft state, prefill from product
                res.update({
                    'line_id': line.id,
                    'jobwork_cost': line.jobwork_cost or (line.product_id.total_jobwork_cost or 0.0),
                    'freight_cost': line.freight_cost or (line.product_id.total_freight_cost or 0.0),
                    'packing_cost': line.packing_cost or (line.product_id.total_packing_cost or 0.0),
                    'cushion': line.cushion or (line.product_id.cushion or 0.0),
                    'gross_profit_add': line.gross_profit_add or (line.product_id.gross_profit_add or 0.0),
                })
            
            # Get level fields from product if they exist
            if hasattr(line.product_id, 'level1Add'):
                res['level1Add'] = line.product_id.level1Add if hasattr(line.product_id, 'level1Add') else 0.0
            else:
                res['level1Add'] = 0.0
                
            if hasattr(line.product_id, 'level2Add'):
                res['level2Add'] = line.product_id.level2Add if hasattr(line.product_id, 'level2Add') else 0.0
            else:
                res['level2Add'] = 0.0
                
            if hasattr(line.product_id, 'level3Add'):
                res['level3Add'] = line.product_id.level3Add if hasattr(line.product_id, 'level3Add') else 0.0
            else:
                res['level3Add'] = 0.0
                
            if hasattr(line.product_id, 'level4Add'):
                res['level4Add'] = line.product_id.level4Add if hasattr(line.product_id, 'level4Add') else 0.0
            else:
                res['level4Add'] = 0.0
                
            # We don't need to get price levels since they are computed fields
            if hasattr(line.product_id, 'include_in_pricelist'):
                res['include_in_pricelist'] = line.product_id.include_in_pricelist or False
            else:
                res['include_in_pricelist'] = False
        
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
        
        # Try to write level fields only if they exist on the model
        try:
            self.line_id.write({
                'level1Add': self.level1Add,
                'level2Add': self.level2Add,
                'level3Add': self.level3Add,
                'level4Add': self.level4Add,
            })
        except Exception:
            # If fields don't exist on the model, just ignore
            pass
            
        # Update with main values that we know exist
        self.line_id.write(values)
        
        # Calculate total cost including additional costs
        new_total = (
            self.line_id.material_cost + 
            self.line_id.operation_cost +
            self.jobwork_cost +
            self.freight_cost +
            self.packing_cost +
            self.cushion +
            self.gross_profit_add
        )
        
        # Calculate other_cost
        other_cost = (
            self.jobwork_cost +
            self.freight_cost +
            self.packing_cost +
            self.cushion +
            self.gross_profit_add
        )
        
        # Update total_cost and other_cost
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
            # Main values
            values = {
                'total_jobwork_cost': self.jobwork_cost,
                'total_freight_cost': self.freight_cost,
                'total_packing_cost': self.packing_cost,
                'cushion': self.cushion,
                'gross_profit_add': self.gross_profit_add,
            }
            
            # Try to write level fields if they exist on the product model
            try:
                self.product_id.write({
                    'level1Add': self.level1Add,
                    'level2Add': self.level2Add,
                    'level3Add': self.level3Add,
                    'level4Add': self.level4Add,
                    'include_in_pricelist': self.include_in_pricelist,
                })
            except Exception:
                # If fields don't exist on the model, just ignore
                pass
                
            # Update with main values
            self.product_id.write(values)
        
        return {'type': 'ir.actions.act_window_close'}