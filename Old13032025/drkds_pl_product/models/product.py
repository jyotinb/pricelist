from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_readonly = fields.Boolean(
        compute="_compute_is_readonly",
        store=False
    )

    total_jobwork_cost = fields.Float("Total Jobwork Cost")
    total_freight_cost = fields.Float("Total Freight Cost")
    total_packing_cost = fields.Float("Total Packing Cost")
    cushion = fields.Float("Cushion")
    gross_profit_add = fields.Float("Gross Profit Add")
    level1Add = fields.Float("Level 1 Addition")
    level2Add = fields.Float("Level 2 Addition")
    level3Add = fields.Float("Level 3 Addition")
    level4Add = fields.Float("Level 4 Addition")
    level1price = fields.Float("Level 1 Price", compute="_compute_level_prices", store=True)
    level2price = fields.Float("Level 2 Price", compute="_compute_level_prices", store=True)
    level3price = fields.Float("Level 3 Price", compute="_compute_level_prices", store=True)
    level4price = fields.Float("Level 4 Price", compute="_compute_level_prices", store=True)
    include_in_pricelist = fields.Boolean("Include in Pricelist", default=False)
    
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
    
    @api.depends('standard_price', 'level1Add', 'level2Add', 'level3Add', 'level4Add')
    def _compute_level_prices(self):
        for product in self:
            calculator = self._get_calculator(product.product_variant_id.id)
            
            # If a calculator is found, use its unit_cost; otherwise, set prices to 0
            if calculator and hasattr(calculator, 'unit_cost'):
                base_cost = calculator.unit_cost
                product.level1price = base_cost + product.level1Add
                product.level2price = product.level1price + product.level2Add
                product.level3price = product.level2price + product.level3Add
                product.level4price = product.level3price + product.level4Add
            else:
                product.level1price = 0.0
                product.level2price = 0.0
                product.level3price = 0.0
                product.level4price = 0.0

    def _check_pricelist_manager(self):
        return self.env.user.has_group('drkds_pl_product.group_pricelist_manager')

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        res = super().fields_get(allfields, attributes)
        is_manager = self._check_pricelist_manager()
        
        cost_fields = [
            'total_jobwork_cost',
            'total_freight_cost',
            'total_packing_cost',
            'cushion',
            'gross_profit_add',
            'level1Add',
            'level2Add',
            'level3Add',
            'level4Add',
            'level1price',
            'level2price',
            'level3price',
            'level4price',
            'include_in_pricelist'
        ]
        
        if not is_manager:
            for field in cost_fields:
                if field in res:
                    res[field]['readonly'] = True
        
        return res