from odoo import api, fields, models

class ProductCostWizard(models.TransientModel):
    _name = 'product.cost.wizard'
    _description = 'Product Cost Update Wizard'

    bom_line_id = fields.Many2one('mrp.bom.line', string='BOM Line', required=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    current_cost = fields.Float(string='Current Cost', readonly=True)
    new_cost = fields.Float(string='New Cost', required=True)

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        if self._context.get('active_id'):
            bom_line = self.env['mrp.bom.line'].browse(self._context.get('active_id'))
            res.update({
                'bom_line_id': bom_line.id,
                'product_id': bom_line.product_id.id,
                'current_cost': bom_line.product_id.standard_price,
                'new_cost': bom_line.product_id.standard_price,
            })
        return res

    def action_update_cost(self):
        self.ensure_one()
        self.product_id.standard_price = self.new_cost
        return {'type': 'ir.actions.act_window_close'}