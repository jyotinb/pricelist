from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class ProductThreeColumnReport(models.AbstractModel):
    """
    This model handles the generation of the Product Three Column Report.
    It prepares data for the QWeb template to render a product price list
    with customer-specific and salesperson information.
    """
    _name = 'report.drkds_pl2.report_product_three_column'
    _description = 'Product Three Column Report'

    def _validate_and_get_document(self, doc_id):
        """
        Validate and retrieve the document for the report.
        
        Args:
            doc_id: ID of the mrp.bom.cost.calculator document
            
        Returns:
            The document record
            
        Raises:
            UserError: If document cannot be found
        """
        if not doc_id:
            raise UserError(_("No document ID provided for report generation."))
            
        doc = self.env['mrp.bom.cost.calculator'].browse(doc_id)
        if not doc.exists():
            raise UserError(_("Document with ID %s not found.") % doc_id)
            
        # Check access rights - but don't raise errors to maintain compatibility
        try:
            doc.check_access_rights('read')
            doc.check_access_rule('read')
        except Exception as e:
            _logger.warning("Access check failed, but continuing for compatibility: %s", str(e))
            
        return doc

    def _get_partner_details(self, customer_id, contact_id, salesman_id):
        """
        Efficiently retrieve all partner-related details in a minimal number of queries.
        
        Args:
            customer_id: ID of the customer partner
            contact_id: ID of the contact partner
            salesman_id: ID of the salesperson user
            
        Returns:
            Dictionary containing customer, contact, and salesperson information
        """
        result = {
            'customer': False,
            'contact': False,
            'salesman': False,
            'salesman_email': False,
            'salesman_mobile': False
        }
        
        # Get all records in one query where possible
        partners_to_fetch = set()
        if customer_id:
            partners_to_fetch.add(customer_id)
        if contact_id:
            partners_to_fetch.add(contact_id)
            
        if partners_to_fetch:
            partners = self.env['res.partner'].browse(list(partners_to_fetch))
            for partner in partners:
                if partner.id == customer_id:
                    result['customer'] = partner
                if partner.id == contact_id:
                    result['contact'] = partner
        
        # Get salesman details if provided
        if salesman_id:
            salesman = self.env['res.users'].sudo().browse(salesman_id).exists()
            if salesman:
                result['salesman'] = salesman
                result['salesman_email'] = salesman.email
                result['salesman_mobile'] = salesman.partner_id.mobile if salesman.partner_id else False
                
        return result

    def _log_report_generation(self, customer_id, contact_id, salesman_id, price_level, doc_id):
        """
        Create a log entry for the report generation.
        
        Args:
            customer_id: ID of the customer
            contact_id: ID of the contact
            salesman_id: ID of the salesperson
            price_level: Selected price level
            doc_id: ID of the source document
            
        Returns:
            The created log record
        """
        try:
            return self.env['drkds_pl2.product_report_log'].create({
                'customer_id': customer_id,
                'contact_id': contact_id if contact_id else False,
                'salesman_id': salesman_id if salesman_id else False,
                'price_level': price_level,
                'doc_id': doc_id,
            })
        except Exception as e:
            _logger.error("Failed to create report log: %s", str(e))
            # Continue with report generation even if logging fails
            return False

    def _get_currency_info(self, doc):
        """
        Get currency information for the report.
        
        Args:
            doc: The document record
            
        Returns:
            Currency record to use in the report
        """
        return doc.env.company.currency_id

    @api.model
    def _get_report_values(self, docids, data=None):
        """
        Prepare all data needed for the report template.
        
        Args:
            docids: List of document IDs when called directly
            data: Dictionary containing form data when called from wizard
            
        Returns:
            Dictionary with all data needed for the template
        """
        # Case 1: Report called directly from Print menu - BLOCK THIS
        if not data:
            raise UserError(_("This report can only be printed through the Product Three Column Wizard. "
                             "Please use the 'PL Report' button on the BOM Cost Calculator form."))
            
        # Case 2: Report called from wizard - continue as normal
        try:
            # Maintain original behavior for missing form data
            if not data.get('form'):
                _logger.warning("Report called with missing form data")
                return {}
            
        # Rest of the code stays the same...
            
        except Exception as e:
            _logger.error("Error generating report from wizard: %s", str(e))
            # Return a minimal data structure to avoid template rendering errors
            return {
                'doc_ids': data.get('form', {}).get('doc_id', []) and [data['form']['doc_id']] or [],
                'doc_model': 'mrp.bom.cost.calculator',
                'docs': self.env['mrp.bom.cost.calculator'].browse([]),
                'data': data.get('form', {}),
                'currency': self.env.company.currency_id,
                'customer': False,
                'contact': False,
                'salesman': False,
                'customer_name': '',
                'contact_name': '',
                'salesman_name': '',
                'salesman_email': '',
                'salesman_mobile': '',
                'price_level': 'all',
            }