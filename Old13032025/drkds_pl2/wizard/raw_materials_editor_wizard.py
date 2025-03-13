from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import json

_logger = logging.getLogger(__name__)

class RawMaterialsEditorWizard(models.TransientModel):
    _name = 'raw.materials.editor.wizard'
    _description = 'Raw Materials Price Editor'

    line_id = fields.Many2one('mrp.bom.cost.calculator.product.line', string='Product Line', required=True)
    product_id = fields.Many2one('product.product', related='line_id.product_id', string='Product', readonly=True)
    bom_id = fields.Many2one('mrp.bom', related='line_id.bom_id', string='BOM', readonly=True)
    material_line_ids = fields.One2many('raw.materials.editor.line', 'wizard_id', string='Raw Materials')
    is_calculated = fields.Boolean('Is Calculated', compute='_compute_is_calculated')
    
    @api.depends('line_id.state')
    def _compute_is_calculated(self):
        for record in self:
            record.is_calculated = record.line_id.state != 'draft'

    @api.model
    def default_get(self, fields_list):
        """Load all raw materials from the BOM and nested BOMs"""
        res = super().default_get(fields_list)
        
        if not self._context.get('active_id'):
            return res
            
        line = self.env['mrp.bom.cost.calculator.product.line'].browse(self._context.get('active_id'))
        res['line_id'] = line.id
        
        if not line.bom_id:
            return res
            
        # Get all raw materials (without BOMs) from all levels
        raw_materials = self._get_all_raw_materials(line.bom_id)
        
        if not raw_materials:
            return res
            
        material_lines = []
        for product, qty in raw_materials.items():
            if not product or not product.id:
                continue  # Skip invalid products
                
            material_lines.append({
                'product_id': product.id,
                'current_price': product.standard_price,
                'new_price': product.standard_price,
                'quantity': qty,
                'total_value': qty * product.standard_price,
            })
            
        res['material_line_ids'] = [(0, 0, line) for line in material_lines]
        return res
        
    def _get_all_raw_materials(self, bom, factor=1.0, level=0, processed_boms=None):
        """Recursively get all raw materials from BOM and nested BOMs"""
        if processed_boms is None:
            processed_boms = set()
            
        if bom.id in processed_boms:
            return {}
            
        processed_boms.add(bom.id)
        raw_materials = {}
        
        for line in bom.bom_line_ids:
            line_qty = line.product_uom_id._compute_quantity(
                line.product_qty, line.product_id.uom_id) * factor
                
            child_bom = self.env['mrp.bom']._bom_find(
                products=line.product_id,
                company_id=bom.company_id.id,
                picking_type=False
            ).get(line.product_id)
            
            if child_bom:
                # If component has a BOM, get its raw materials
                child_factor = line_qty / (child_bom.product_qty or 1.0)
                child_materials = self._get_all_raw_materials(
                    child_bom, 
                    factor=child_factor,
                    level=level + 1,
                    processed_boms=processed_boms.copy()
                )
                
                # Merge with current raw materials
                for product, qty in child_materials.items():
                    raw_materials[product] = raw_materials.get(product, 0.0) + qty
            else:
                # Raw material (no BOM)
                if line.product_id in raw_materials:
                    raw_materials[line.product_id] += line_qty
                else:
                    raw_materials[line.product_id] = line_qty
                    
        return raw_materials
        
    def action_recalculate_values(self):
        """Recalculate total values based on new prices - only updates the wizard"""
        for line in self.material_line_ids:
            line.total_value = line.quantity * line.new_price
        return {"type": "ir.actions.do_nothing"}

    def action_update_calculation_only(self):
        """Update prices for current calculation only - doesn't change product master"""
        self.ensure_one()
        
        if self.line_id.state != 'draft':
            raise UserError(_("Cannot modify material prices after calculation. Reset to draft first."))
            
        # Store the changes in a temporary field on the calculator line
        temp_updates = {}
        for line in self.material_line_ids:
            if line.current_price != line.new_price:
                # Make sure we're storing product IDs as strings for JSON compatibility
                temp_updates[str(line.product_id.id)] = line.new_price
                
        # Store this as JSON on the calculator line for later use during calculation
        self.line_id.write({
            'temp_material_price_updates': json.dumps(temp_updates)
        })
                
        return {'type': 'ir.actions.act_window_close'}
    
    def action_update_product_master(self):
        """Update standard prices for all raw materials in product master"""
        self.ensure_one()
        
        if self.line_id.state != 'draft':
            raise UserError(_("Cannot modify material prices after calculation. Reset to draft first."))
            
        modified_products = []
        # Update prices for all changed materials
        for line in self.material_line_ids:
            if line.current_price != line.new_price:
                line.product_id.standard_price = line.new_price
                modified_products.append(line.product_id.display_name)
                
        if modified_products:
            message = _("Updated standard prices for: %s") % ", ".join(modified_products)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Prices Updated'),
                    'message': message,
                    'sticky': False,
                    'type': 'success',
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        else:
            return {'type': 'ir.actions.act_window_close'}


class RawMaterialsEditorLine(models.TransientModel):
    _name = 'raw.materials.editor.line'
    _description = 'Raw Materials Editor Line'
    
    wizard_id = fields.Many2one('raw.materials.editor.wizard', string='Wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Material', required=True, readonly=True)
    current_price = fields.Float('Current Price', digits='Product Price', readonly=True)
    new_price = fields.Float('New Price', digits='Product Price')
    quantity = fields.Float('Quantity', digits='Product Unit of Measure', readonly=True)
    total_value = fields.Float('Total Value', digits='Product Price')
    price_difference = fields.Float('Price Difference (%)', compute='_compute_price_difference')
    
    @api.depends('current_price', 'new_price')
    def _compute_price_difference(self):
        for record in self:
            if record.current_price:
                record.price_difference = ((record.new_price / record.current_price) - 1.0) * 100
            else:
                record.price_difference = 0.0
    
    @api.onchange('new_price')
    def _onchange_new_price(self):
        self.total_value = self.quantity * self.new_price