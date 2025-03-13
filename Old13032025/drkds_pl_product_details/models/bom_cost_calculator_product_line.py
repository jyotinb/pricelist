from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class BOMCostCalculatorProductLine(models.Model):
    _inherit = 'mrp.bom.cost.calculator.product.line'
    
    def action_view_cost_details(self):
        """Open the cost details wizard for this product line"""
        self.ensure_one()
        
        if self.state == 'draft':
            raise UserError(_("Please calculate costs first to view details."))
            
        if not self.is_manufacture or not self.bom_id:
            raise UserError(_("Detailed cost view is only available for products with BOMs."))
            
        # Create wizard first to ensure it generates correctly
        wizard = self.env['product.cost.details.wizard'].create({
            'calculator_id': self.calculator_id.id,
            'product_line_id': self.id,
        })
        
        # Try to find the view
        view_id = False
        try:
            view_id = self.env.ref('drkds_pl_product_details.view_product_cost_details_wizard_form')
        except ValueError:
            _logger.warning("Could not find view_product_cost_details_wizard_form")
            # If we can't find the view, Odoo will use a default one
        
        return {
            'name': _('Cost Breakdown for %s') % self.product_id.display_name,
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'product.cost.details.wizard',
            'res_id': wizard.id,
            'view_id': view_id.id if view_id else False,
            'target': 'new',
            'context': {
                'form_view_initial_mode': 'readonly',
            },
        }