from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class ProductCostDetailsWizard(models.TransientModel):
    _name = 'product.cost.details.wizard'
    _description = 'Product Cost Details Wizard'

    calculator_id = fields.Many2one('mrp.bom.cost.calculator', string='Calculator', required=True)
    product_line_id = fields.Many2one('mrp.bom.cost.calculator.product.line', string='Product Line', required=True)
    product_id = fields.Many2one('product.product', related='product_line_id.product_id', string='Product', readonly=True)
    bom_id = fields.Many2one('mrp.bom', related='product_line_id.bom_id', string='Bill of Materials', readonly=True)
    
    # To store the calculated cost details
    cost_details_ids = fields.One2many('product.cost.details.wizard.line', 'wizard_id', 'Cost Details')
    
    # Summary fields
    material_cost = fields.Float('Total Material Cost', readonly=True)
    operation_cost = fields.Float('Total Operation Cost', readonly=True)
    other_cost = fields.Float('Total Additional Cost', readonly=True, compute='_compute_other_cost')
    total_cost = fields.Float('Total Cost', readonly=True, compute='_compute_total_cost')
    unit_cost = fields.Float('Unit Cost', readonly=True, compute='_compute_unit_cost')
    
    @api.depends('product_line_id')
    def _compute_other_cost(self):
        for record in self:
            if record.product_line_id:
                record.other_cost = record.product_line_id.other_cost
            else:
                record.other_cost = 0.0
    
    @api.depends('material_cost', 'operation_cost', 'other_cost')
    def _compute_total_cost(self):
        for record in self:
            record.total_cost = record.material_cost + record.operation_cost + record.other_cost
            
            
    @api.depends('total_cost', 'bom_id')
    def _compute_unit_cost(self):
        for record in self:
            if record.bom_id and record.bom_id.product_qty > 0:
                record.unit_cost = record.total_cost / record.bom_id.product_qty
            else:
                record.unit_cost = record.total_cost
    
    @api.model
    def default_get(self, fields_list):
        """Load the values from the selected line"""
        res = super().default_get(fields_list)
        
        if self._context.get('active_id'):
            line = self.env['mrp.bom.cost.calculator.product.line'].browse(self._context.get('active_id'))
            calculator = line.calculator_id
            
            if not line.bom_id:
                raise UserError(_("This product does not have a Bill of Materials assigned."))
            
            # Store basic info
            res.update({
                'calculator_id': calculator.id,
                'product_line_id': line.id,
            })
            
        return res
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create to generate cost details"""
        wizards = super().create(vals_list)
        for wizard in wizards:
            wizard._generate_cost_details()
        return wizards
    
    def _generate_cost_details(self):
        """Generate detailed cost breakdown using an implementation that matches the original"""
        self.ensure_one()
        
        # Clear existing lines
        self.cost_details_ids.unlink()
        
        if not self.bom_id or not self.product_id:
            return
            
        # Calculate costs using exact same algorithm as original
        material_cost, operation_cost, _ = self._calculate_bom_cost(self.bom_id)
        
        # Update summary fields
        self.material_cost = material_cost
        self.operation_cost = operation_cost
    
    def _calculate_bom_cost(self, bom, processed_boms=None, level=0):
        """
        Implementation that closely matches the original _calculate_bom_cost method
        to ensure costs are calculated the same way
        """
        if not bom:
            return 0, 0, 0
            
        # Use product from the product_line
        product_to_use = self.product_id
                
        if processed_boms is None:
            processed_boms = set()
                
        if bom.id in processed_boms:
            return 0, 0, 0
        processed_boms.add(bom.id)
            
        material_total = 0
        operation_total = 0
        total_duration = 0

        # Operation costs
        include_operations = self.calculator_id.include_operations
        if include_operations:
            for operation in bom.operation_ids:
                if hasattr(operation, '_skip_operation_line') and operation._skip_operation_line(product_to_use):
                    continue
                        
                duration_expected = (
                    operation.time_cycle or 
                    operation.time_cycle_manual or 
                    operation.duration_expected or 
                    0.0
                )
                
                total_duration += duration_expected
                
                cost_per_minute = operation._total_cost_per_hour() / 60
                operation_cost = duration_expected * cost_per_minute
                    
                # Create operation cost line
                self.env['product.cost.details.wizard.line'].create({
                    'wizard_id': self.id,
                    'name': f"{bom.product_tmpl_id.display_name} - {operation.workcenter_id.name} ({operation.name or 'Operation'})",
                    'cost_type': 'operation',
                    'operation_id': operation.id,
                    'duration': duration_expected,
                    'unit_cost': operation._total_cost_per_hour(),
                    'cost': operation_cost,
                    'bom_level': level,
                    'bom_qty': bom.product_qty,
                })

                operation_total += operation_cost

        # Material costs
        for line in bom.bom_line_ids:
            if hasattr(line, '_skip_bom_line') and line._skip_bom_line(product_to_use):
                continue

            line_qty = line.product_uom_id._compute_quantity(
                line.product_qty, line.product_id.uom_id)

            child_bom = self.env['mrp.bom']._bom_find(
                products=line.product_id,
                company_id=bom.company_id.id,
                picking_type=False
            ).get(line.product_id)

            if child_bom:
                # For components with BOMs, we only pass through their costs 
                # without adding new material costs
                child_material, child_operation, child_duration = self._calculate_bom_cost(
                    child_bom, 
                    processed_boms.copy(),
                    level=level + 1
                )
                
                # Add child costs considering the quantity ratio
                qty_ratio = line_qty / (child_bom.product_qty or 1.0)
                child_material_cost = child_material * qty_ratio
                child_operation_cost = child_operation * qty_ratio
                
                material_total += child_material_cost
                operation_total += child_operation_cost
                total_duration += child_duration * qty_ratio
                
                # Add component line
                self.env['product.cost.details.wizard.line'].create({
                    'wizard_id': self.id,
                    'name': f"{line.product_id.display_name} (Component from BOM)",
                    'cost_type': 'material',
                    'product_id': line.product_id.id,
                    'quantity': line_qty,
                    'unit_cost': (child_material / (child_bom.product_qty or 1.0)) if child_bom.product_qty else 0,
                    'cost': child_material_cost,
                    'bom_level': level,
                    'bom_qty': bom.product_qty,
                })
                
            else:
                # Only add material cost for raw materials (no BOM)
                component_cost = line.product_id.standard_price * line_qty
                material_total += component_cost

                # Add raw material line
                self.env['product.cost.details.wizard.line'].create({
                    'wizard_id': self.id,
                    'name': f"{line.product_id.display_name} (Raw Material)",
                    'cost_type': 'material',
                    'product_id': line.product_id.id,
                    'quantity': line_qty,
                    'unit_cost': line.product_id.standard_price,
                    'cost': component_cost,
                    'bom_level': level,
                    'bom_qty': bom.product_qty,
                })

        return material_total, operation_total, total_duration
    
    def action_close(self):
        """Close the wizard"""
        return {'type': 'ir.actions.act_window_close'}


class ProductCostDetailsWizardLine(models.TransientModel):
    _name = 'product.cost.details.wizard.line'
    _description = 'Product Cost Details Wizard Line'

    wizard_id = fields.Many2one('product.cost.details.wizard', 'Wizard', required=True, ondelete='cascade')
    name = fields.Char('Description', required=True)
    cost_type = fields.Selection([
        ('material', 'Material'),
        ('operation', 'Operation')
    ], string='Cost Type', required=True)
    product_id = fields.Many2one('product.product', 'Component')
    operation_id = fields.Many2one('mrp.routing.workcenter', 'Operation')
    quantity = fields.Float('Quantity', digits='Product Unit of Measure')
    duration = fields.Float('Duration (minutes)')
    unit_cost = fields.Float('Unit Cost', digits='Product Price')
    cost = fields.Float('Cost', digits='Product Price')
    bom_level = fields.Integer('BOM Level', default=0)
    bom_qty = fields.Float('BOM Production Qty', digits='Product Unit of Measure')