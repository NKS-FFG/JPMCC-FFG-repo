from odoo import fields, models, api, _
from odoo.exceptions import ValidationError

class ClusterDraftProducts(models.Model):
    _name = 'cluster.draft.products'
    _description = 'Cluster Draft Products'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    productName = fields.Char(string='Draft Product Name', required=True, tracking=True)
    description = fields.Char(string='Description', tracking=True)
    # image = fields.Many2many('ir.attachment', string="Image", required=True, tracking=True)
    image_1 = fields.Binary("Image 1", attachment=True)
    image_1_filename = fields.Char("Image 1 Filename")

    image_2 = fields.Binary("Image 2", attachment=True)
    image_2_filename = fields.Char("Image 2 Filename")

    image_3 = fields.Binary("Image 3", attachment=True)
    image_3_filename = fields.Char("Image 3 Filename")

    main_image = fields.Binary("Main Image", compute='_compute_main_image', store=True)

    @api.depends('image_1', 'image_2', 'image_3')
    def _compute_main_image(self):
        for product in self:
            if product.image_1:
                product.main_image = product.image_1
            elif product.image_2:
                product.main_image = product.image_2
            elif product.image_3:
                product.main_image = product.image_3
            else:
                product.main_image = False

    productCategory = fields.Many2one('product.public.category', string='Product Category', required=True, tracking=True)
    covering_material = fields.Char(string='Covering Material', tracking=True)
    dimensions = fields.Char(string='Dimensions', tracking=True)
    other_remarks = fields.Text(string='Other Remarks', tracking=True)
    tentative_price = fields.Float(string='Tentative Price', tracking=True)

    @api.model
    def _default_cluster_head_user(self):
        cluster_head_group = self.env.ref('cluster_image_screen.cluster_head')
        if cluster_head_group in self.env.user.groups_id:
            return self.env.user.id
        return False
    
    @api.model
    def _get_cluster_head_domain(self):
        cluster_head_group = self.env.ref('cluster_image_screen.cluster_head') # IMP: Assuming 'cluster_image_screen.cluster_head' is the XML ID of the cluster head group
        return [('groups_id', 'in', [cluster_head_group.id])]
    
    clusterHeadUserId = fields.Many2one('res.users', 
        string='Cluster Head User', 
        required=True, 
        domain=lambda self: self._get_cluster_head_domain(),
        default=_default_cluster_head_user,
        tracking=True
    )
    submit_status = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Submit Status', default='draft', tracking=True)
    def action_approve_product(self):
        for record in self:
            if record.submit_status != 'draft':
                raise ValidationError("You can only submit draft records.")

            required_fields = [
                ('productName', 'Product Name'),
                ('productCategory', 'Product Category'),
                ('clusterHeadUserId', 'Cluster Head'),
            ]
            missing = [label for field, label in required_fields if not getattr(record, field)]
            if missing:
                raise ValidationError(f"Please fill all required fields before submitting: {', '.join(missing)}.")

            record.submit_status = 'submitted'

    is_submit_button_disabled = fields.Boolean(compute='_compute_editability',default=False,
        store=False
    )
    is_approve_button_invisible = fields.Boolean(compute='_compute_editability', store=False, default=True)
    form_readonly = fields.Boolean(compute='_compute_editability', store=False)

    @api.depends()
    def _compute_editability(self):
        for rec in self:
            rec.form_readonly = True
            rec.is_submit_button_disabled = True
            rec.is_approve_button_invisible = True
            if rec.submit_status == 'draft':
                rec.form_readonly = False
                rec.is_submit_button_disabled = False
                rec.is_approve_button_invisible = True
            elif rec.submit_status == 'approved' or rec.submit_status == 'rejected':
                rec.is_approve_button_invisible = True
                rec.form_readonly = True
            elif self.env.user.has_group('cluster_image_screen.cluster_head'):
                rec.form_readonly = True
            elif self.env.user.has_group('cluster_image_screen.cluster_reviewer') or self.env.user.has_group('base.group_system') :
                rec.form_readonly = False
                rec.is_approve_button_invisible = False
    

    def convert_to_ecommerce_product(self):
        for draft in self:
            if draft.submit_status != 'submitted':
                raise ValidationError("Only approved draft products can be published to eCommerce.")

            if not draft.main_image:
                raise ValidationError("At least one image is required to publish the product.")

            # Use the first image as the main product image
            main_image1 = draft.main_image

            product_vals = {
                'name': draft.productName,
                'description_ecommerce': draft.description,
                'website_published': True,
                'public_categ_ids': [(6, 0, [draft.productCategory.id])],
                'sale_ok': True,
                'list_price': draft.tentative_price or 0.0,
                'categ_id': self.env.ref('product.product_category_all').id,
                'image_1920': main_image1,
                'dimensions':draft.dimensions,
                'other_remarks': draft.other_remarks,
                'covering_material': draft.covering_material
            }

            product = self.env['product.template'].create(product_vals)

            # Copy each image attachment
            # for image in draft.image[1:]:
            #     self.env['product.image'].create({
            #         'product_tmpl_id': product.id,
            #         'name': image.name,
            #         'image_1920': image.datas,  # Assuming image is in image field of ir.attachment
            #     })

            if draft.image_2 and draft.main_image != draft.image_2:
                self.env['product.image'].create({
                    'product_tmpl_id': product.id,
                    'name': draft.productName + ' - Image 2',
                    'image_1920': draft.image_2,  # Assuming image is in image field of ir.attachment
                })

            if draft.image_3 and draft.main_image != draft.image_3:
                self.env['product.image'].create({
                    'product_tmpl_id': product.id,
                    'name': draft.productName + ' - Image 3',
                    'image_1920': draft.image_3,  # Assuming image is in image field of ir.attachment
                })

            # Optional: update status or mark draft as converted
            draft.write({'submit_status': 'approved'})  # Add 'published' if needed
    
    def reject_product(self):
        for record in self:
            record.submit_status = 'rejected'
            record.is_approve_button_invisible = False
            record.form_readonly = True


from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    covering_material = fields.Char(string='Covering Material', tracking=True)
    dimensions = fields.Char(string='Dimensions', tracking=True)
    other_remarks = fields.Text(string='Other Remarks', tracking=True)


