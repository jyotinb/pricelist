from odoo import models, fields, api, _


class ProductThreeColumnReport(models.AbstractModel):
    _name = 'report.drkds_pl2.report_product_three_column'
    _description = 'Product Three Column Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data:
            # Report called directly from Print menu
            docs = self.env['mrp.bom.cost.calculator'].browse(docids)
            return {
                'doc_ids': docids,
                'doc_model': 'mrp.bom.cost.calculator',
                'docs': docs,
                'data': None,
            }
        
        if not data.get('form'):
            return {}
            
        # Extract parameters from the wizard
        customer_id = data['form']['customer_id']
        customer_name = data['form']['customer_name']
        contact_id = data['form']['contact_id']
        contact_name = data['form']['contact_name']
        salesman_id = data['form']['salesman_id']
        salesman_name = data['form']['salesman_name']
        price_level = data['form']['price_level']
        doc_id = data['form']['doc_id']
        is_multi_product = data['form']['is_multi_product']
        
        # Get the document
        doc = self.env['mrp.bom.cost.calculator'].browse(doc_id)
        
        # Get additional info if needed
        customer = self.env['res.partner'].browse(customer_id) if customer_id else False
        contact = self.env['res.partner'].browse(contact_id) if contact_id else False
        
        # Get salesman and their contact details
        salesman = self.env['res.users'].browse(salesman_id) if salesman_id else False
        salesman_email = salesman.email if salesman else False
        salesman_mobile = salesman.partner_id.mobile if salesman and salesman.partner_id else False
        
        return {
            'doc_ids': [doc_id],
            'doc_model': 'mrp.bom.cost.calculator',
            'docs': doc,
            'data': data['form'],
            'customer': customer,
            'contact': contact,
            'salesman': salesman,
            'customer_name': customer_name,
            'contact_name': contact_name,
            'salesman_name': salesman_name,
            'salesman_email': salesman_email,
            'salesman_mobile': salesman_mobile,
            'price_level': price_level,
        }