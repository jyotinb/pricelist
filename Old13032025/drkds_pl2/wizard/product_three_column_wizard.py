# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class ProductThreeColumnWizard(models.TransientModel):
    _name = 'drkds_pl2.product_three_column_wizard'
    _description = 'Product Three Column Report Wizard'

    customer_id = fields.Many2one('res.partner', string='Customer', domain=[('customer_rank', '>', 0)], required=True)
    contact_id = fields.Many2one('res.partner', string='Contact', domain="[('parent_id', '=', customer_id)]")
    salesman_id = fields.Many2one('res.users', string='Salesman', domain=[('share', '=', False)])
    price_level = fields.Selection([
        ('1', 'Price Level 1'),
        ('2', 'Price Level 2'),
        ('3', 'Price Level 3'),
        ('4', 'Price Level 4'),
        ('all', 'All Price Levels'),
    ], string='Price Level', default='all', required=True)
    doc_id = fields.Many2one('mrp.bom.cost.calculator', string='Cost Calculator Document', readonly=True)
    is_multi_product = fields.Boolean(related='doc_id.is_multi_product', readonly=True)

    @api.onchange('customer_id')
    def _onchange_customer_id(self):
        """Clear contact when customer changes"""
        self.contact_id = False
    
    def action_print_report(self):
        """Launch the report with the selected parameters"""
        self.ensure_one()
        
        # Create a log record
        self.env['drkds_pl2.product_report_log'].create({
            'customer_id': self.customer_id.id,
            'contact_id': self.contact_id.id if self.contact_id else False,
            'salesman_id': self.salesman_id.id if self.salesman_id else False,
            'price_level': self.price_level,
            'doc_id': self.doc_id.id,
        })
        
        # Prepare the data to send to the report
        data = {
            'ids': self.ids,
            'model': self._name,
            'form': {
                'customer_id': self.customer_id.id,
                'customer_name': self.customer_id.name,
                'contact_id': self.contact_id.id if self.contact_id else False,
                'contact_name': self.contact_id.name if self.contact_id else '',
                'salesman_id': self.salesman_id.id if self.salesman_id else False,
                'salesman_name': self.salesman_id.name if self.salesman_id else '',
                # 'salesman_email': salesman_email,
                # 'salesman_mobile': salesman_mobile,
                'price_level': self.price_level,
                'doc_id': self.doc_id.id,
                'is_multi_product': self.is_multi_product,
            }
        }
        
        # Return action to open the report
        return self.env.ref('drkds_pl2.action_report_product_three_column').report_action(self.doc_id, data=data)