from odoo import models, fields, api, _, tools
from odoo.exceptions import UserError, ValidationError
import logging
import json
import uuid

_logger = logging.getLogger(__name__)

class RawMaterialsEditorWizard(models.TransientModel):
    _name = 'raw.materials.editor.wizard'
    _description = 'Raw Materials Price Editor'

    # Core Identification Fields
    line_id = fields.Many2one(
        'mrp.bom.cost.calculator.product.line', 
        string='Product Line', 
        required=True,
        domain="[('calculator_id.state', '=', 'draft')]",
        help="Related product line for cost calculation"
    )
    
    product_id = fields.Many2one(
        'product.product', 
        related='line_id.product_id', 
        string='Product', 
        readonly=True,
        help="Product being analyzed"
    )
    
    bom_id = fields.Many2one(
        'mrp.bom', 
        related='line_id.bom_id', 
        string='Bill of Materials', 
        readonly=True,
        help="Bill of Materials for the product"
    )
    
    # Raw Materials Collection
    material_line_ids = fields.One2many(
        'raw.materials.editor.line', 
        'wizard_id', 
        string='Raw Materials',
        help="Detailed raw materials from BOM"
    )
    
    # Tracking and State Management
    is_calculated = fields.Boolean(
        'Is Calculated', 
        compute='_compute_is_calculated',
        help="Indicates if the line has been calculated"
    )
    
    batch_id = fields.Char(
        'Batch Identifier', 
        default=lambda self: str(uuid.uuid4()),
        readonly=True,
        help="Unique identifier for this edit session"
    )
    
    # Computed Fields and Methods
    @api.depends('line_id.state')
    def _compute_is_calculated(self):
        """Determine calculation state"""
        for record in self:
            record.is_calculated = record.line_id.state != 'draft'
    
    @api.model
    def default_get(self, fields_list):
        """
        Load raw materials with comprehensive extraction
        """
        res = super().default_get(fields_list)
        
        if not self._context.get('active_id'):
            return res
            
        line = self.env['mrp.bom.cost.calculator.product.line'].browse(self._context.get('active_id'))
        res['line_id'] = line.id
        
        if not line.bom_id:
            return res
        
        # Advanced raw materials extraction
        raw_materials = self._get_comprehensive_raw_materials(line.bom_id)
        
        if not raw_materials:
            return res
        
        material_lines = []
        for product, details in raw_materials.items():
            if not product or not product.id:
                continue
            
            material_lines.append({
                'product_id': product.id,
                'current_price': product.standard_price,
                'new_price': product.standard_price,
                'quantity': details['quantity'],
                'total_value': details['quantity'] * product.standard_price,
                'bom_levels': json.dumps(details.get('bom_levels', [])),
                'is_raw_material': details.get('is_raw_material', False)
            })
        
        res['material_line_ids'] = [(0, 0, line) for line in material_lines]
        return res
    
    def _get_comprehensive_raw_materials(self, bom, depth=5, processed_boms=None):
        """
        Advanced raw materials extraction with multi-level support
        """
        if processed_boms is None:
            processed_boms = set()
        
        if depth <= 0 or bom.id in processed_boms:
            return {}
        
        processed_boms.add(bom.id)
        raw_materials = {}
        
        for line in bom.bom_line_ids:
            # Precise quantity computation
            line_qty = line.product_uom_id._compute_quantity(
                line.product_qty, line.product_id.uom_id
            )
            
            # Advanced BOM finding
            child_boms = self.env['mrp.bom'].search([
                ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id),
                ('company_id', '=', bom.company_id.id)
            ])
            
            # Select most appropriate BOM
            child_bom = self._select_most_appropriate_bom(child_boms, line.product_id)
            
            if child_bom:
                # Recursive extraction
                child_materials = self._get_comprehensive_raw_materials(
                    child_bom, 
                    depth=depth-1, 
                    processed_boms=processed_boms.copy()
                )
                
                # Merge child materials
                for child_product, child_details in child_materials.items():
                    existing = raw_materials.get(child_product, {})
                    raw_materials[child_product] = {
                        'quantity': (existing.get('quantity', 0) + 
                                     child_details['quantity'] * line_qty),
                        'bom_levels': list(set(
                            existing.get('bom_levels', []) + 
                            child_details.get('bom_levels', [])
                        )),
                        'is_raw_material': child_details.get('is_raw_material', False)
                    }
            else:
                # Raw material handling
                if line.product_id in raw_materials:
                    raw_materials[line.product_id]['quantity'] += line_qty
                else:
                    raw_materials[line.product_id] = {
                        'quantity': line_qty,
                        'bom_levels': [len(processed_boms)],
                        'is_raw_material': True
                    }
        
        return raw_materials
    
    def _select_most_appropriate_bom(self, boms, product):
        """
        Intelligent BOM selection strategy
        """
        priority_boms = boms.filtered(lambda b: 
            b.active and 
            b.product_tmpl_id == product.product_tmpl_id
        )
        
        if not priority_boms:
            return False
        
        return priority_boms.sorted(
            key=lambda b: (b.create_date, b.product_qty), 
            reverse=True
        )[0]
    
    def action_recalculate_values(self):
        """Recalculate total values based on new prices"""
        for line in self.material_line_ids:
            line.total_value = line.quantity * line.new_price
        return {"type": "ir.actions.do_nothing"}
    
    def action_update_calculation_only(self):
        """
        Update prices for current calculation only
        Supports temporary price modifications
        """
        self.ensure_one()
        
        if self.line_id.state != 'draft':
            raise UserError(_("Cannot modify material prices after calculation. Reset to draft first."))
        
        # Prepare detailed price updates
        temp_updates = {}
        modified_products = []
        
        for line in self.material_line_ids:
            if line.current_price != line.new_price:
                temp_updates[str(line.product_id.id)] = {
                    'old_price': line.current_price,
                    'new_price': line.new_price,
                    'quantity': line.quantity
                }
                modified_products.append(line.product_id.display_name)
        
        # Store updates with additional metadata
        update_log = {
            'batch_id': self.batch_id,
            'timestamp': fields.Datetime.now(),
            'modified_products': modified_products,
            'updates': json.dumps(temp_updates)
        }
        
        self.line_id.write({
            'temp_material_price_updates': json.dumps(update_log)
        })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Temporary Price Updates'),
                'message': _("%s products updated for this calculation") % len(modified_products),
                'sticky': False,
                'type': 'success'
            }
        }
    
    def action_update_product_master(self):
        """
        Comprehensive product master price update
        """
        self.ensure_one()
        
        if self.line_id.state != 'draft':
            raise UserError(_("Cannot modify material prices after calculation. Reset to draft first."))
        
        # Prepare price changes
        price_changes = {}
        for line in self.material_line_ids:
            if line.current_price != line.new_price:
                price_changes[str(line.product_id.id)] = {
                    'new_price': line.new_price
                }
        
        # Use new update method
        update_wizard = self.env['product.price.update.wizard']
        result = update_wizard.update_product_master_prices(price_changes)
        
        # Return notification based on update result
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Product Price Update'),
                'message': result['message'],
                'sticky': not result['success'],
                'type': 'success' if result['success'] else 'warning',
                'next': {'type': 'ir.actions.act_window_close'}
            }
        }

class RawMaterialsEditorLine(models.TransientModel):
    _name = 'raw.materials.editor.line'
    _description = 'Raw Materials Editor Line'
    
    wizard_id = fields.Many2one(
        'raw.materials.editor.wizard', 
        string='Wizard', 
        required=True, 
        ondelete='cascade'
    )
    
    product_id = fields.Many2one(
        'product.product', 
        string='Material', 
        required=True, 
        readonly=True
    )
    
    current_price = fields.Float(
        'Current Price', 
        digits='Product Price', 
        readonly=True
    )
    
    new_price = fields.Float(
        'New Price', 
        digits='Product Price'
    )
    
    quantity = fields.Float(
        'Quantity', 
        digits='Product Unit of Measure', 
        readonly=True
    )
    
    total_value = fields.Float(
        'Total Value', 
        digits='Product Price', 
        compute='_compute_total_value', 
        store=True
    )
    
    bom_levels = fields.Char(
        'BOM Levels', 
        help="Levels in Bill of Materials hierarchy"
    )
    
    is_raw_material = fields.Boolean(
        'Is Raw Material', 
        help="Indicates if this is a true raw material"
    )
    
    price_difference = fields.Float(
        'Price Difference (%)', 
        compute='_compute_price_difference', 
        help="Percentage change in price"
    )
    
    @api.depends('current_price', 'new_price')
    def _compute_price_difference(self):
        for record in self:
            if record.current_price:
                record.price_difference = ((record.new_price / record.current_price) - 1.0) * 100
            else:
                record.price_difference = 0.0
    
    @api.depends('quantity', 'new_price')
    def _compute_total_value(self):
        for record in self:
            record.total_value = record.quantity * record.new_price