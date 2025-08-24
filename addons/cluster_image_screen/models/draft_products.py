from odoo import fields, models, api, _
from odoo.exceptions import ValidationError, UserError
import base64
import requests
from ..comparison.app import compare_multiple_images

class ClusterMatchResult(models.Model):
    _name = 'cluster.match.result'
    _description = 'Similarity Match Result'

    cluster_product_id = fields.Many2one('cluster.draft.products', string="Draft Product", ondelete='cascade')
    similarity = fields.Float(string="Similarity")
    match_id = fields.Many2one('ir.attachment', string="Matched Image")
    image_url = fields.Char(string="Image URL", compute='_compute_image_url')
    filename = fields.Char(string="Match") 
    image_display = fields.Html(string="Image Preview", compute='_compute_image_display')

    @api.depends('match_id')
    def _compute_image_url(self):
        for record in self:
            if record.match_id:
                record.image_url = f'/web/content/{record.match_id.id}'
            else:
                record.image_url = ''

    @api.depends('image_url')
    def _compute_image_display(self):
        for record in self:
            if record.image_url:
                record.image_display = f'<img src="{record.image_url}" alt="Product Image" style="max-width: 100px; max-height: 100px; border-radius: 5px;"/>'
            else:
                record.image_display = ''

class ClusterDraftProducts(models.Model):
    _name = 'cluster.draft.products'
    _description = 'Cluster Draft Products'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    productName = fields.Char(string='Draft Product Name', required=True, tracking=True)
    description = fields.Char(string='Description', tracking=True)

    # Use Many2many for multiple image attachments
    image = fields.Many2many('ir.attachment', string="Image Attachments")

    # Updated to handle multiple images
    image_preview = fields.Html(
        string="Image Preview", compute="_compute_image_preview", store=False
    )

    # ✨ FIX 2: Update the compute method to build an HTML string of images
    @api.depends('image')
    def _compute_image_preview(self):
        for record in self:
            if record.image:
                # Build an HTML string with all images
                images_html = ''
                for img in record.image:
                    # Use /web/content/ for a direct URL to the attachment
                    images_html += f'<img src="/web/content/{img.id}" style="max-height: 120px; max-width: 120px; margin: 5px; border-radius: 8px; border: 1px solid #ddd;" alt="{img.name}"/>'
                record.image_preview = images_html
            else:
                record.image_preview = False

    main_image = fields.Binary("Main Image", compute='_compute_main_image', store=True)

    # ✨ FIX 3: Correct the main_image compute method to avoid the singleton error
    @api.depends('image')
    def _compute_main_image(self):
        for product in self:
            if product.image:
                # Explicitly take the data from the FIRST image in the recordset
                product.main_image = product.image[0].datas
            else:
                product.main_image = False

    cluster_product_id = fields.Many2one('cluster.draft.products', string="Product", ondelete='cascade')
    match_ids = fields.One2many('cluster.match.result', 'cluster_product_id', string="Similarity Matches")

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
        cluster_head_group = self.env.ref('cluster_image_screen.cluster_head')
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
    is_compare_button_invisible = fields.Boolean(compute='_compute_editability', store=False, default=True)
    is_similarity_result_invisible = fields.Boolean(compute='_compute_editability', default=True, store=False)
    form_readonly = fields.Boolean(compute='_compute_editability', store=False)

    @api.depends('submit_status') # Added dependency for better reactivity
    def _compute_editability(self):
        for rec in self:
            is_reviewer = self.env.user.has_group('cluster_image_screen.cluster_reviewer') or self.env.user.has_group('base.group_system')
            is_head = self.env.user.has_group('cluster_image_screen.cluster_head')

            if rec.submit_status == 'draft':
                rec.form_readonly = False
                rec.is_submit_button_disabled = False
                rec.is_approve_button_invisible = True
                rec.is_compare_button_invisible = True
                rec.is_similarity_result_invisible = True
            elif rec.submit_status == 'submitted':
                rec.form_readonly = not is_reviewer
                rec.is_submit_button_disabled = True
                rec.is_approve_button_invisible = not is_reviewer
                rec.is_compare_button_invisible = not is_reviewer
                rec.is_similarity_result_invisible = not is_reviewer
            else: # approved or rejected
                rec.form_readonly = True
                rec.is_submit_button_disabled = True
                rec.is_approve_button_invisible = True
                rec.is_compare_button_invisible = True
                rec.is_similarity_result_invisible = is_reviewer # Reviewers can still see results

    def convert_to_ecommerce_product(self):
        for draft in self:
            if draft.submit_status != 'submitted':
                raise ValidationError("Only submitted draft products can be published to eCommerce.")

            if not draft.main_image:
                raise ValidationError("A main image is required to publish the product.")

            product_vals = {
                'name': draft.productName,
                'description_ecommerce': draft.description,
                'website_published': True,
                'public_categ_ids': [(6, 0, [draft.productCategory.id])],
                'sale_ok': True,
                'list_price': draft.tentative_price or 0.0,
                'categ_id': self.env.ref('product.product_category_all').id,
                'image_1920': draft.main_image,
                'dimensions': draft.dimensions,
                'other_remarks': draft.other_remarks,
                'covering_material': draft.covering_material
            }

            product = self.env['product.template'].create(product_vals)

            # Create product.image records for the other images
            # Starts from the second image (index 1)
            for image_attachment in draft.image[1:]:
                self.env['product.image'].create({
                    'product_tmpl_id': product.id,
                    'name': image_attachment.name,
                    'image_1920': image_attachment.datas,
                })

            draft.write({'submit_status': 'approved'})
    
    def reject_product(self):
        for record in self:
            record.submit_status = 'rejected'

    def compare_button(self):
        for record in self:
            if not record.image:
                raise UserError("Please upload an image to compare.")

            # Send the first image only
            attachment = record.image[0]
            image_binary = base64.b64decode(attachment.datas)
            files = {'image': (attachment.name, image_binary, attachment.mimetype)}

            try:
                response = requests.post('http://localhost:5001/compare', files=files)
                response.raise_for_status()
                data = response.json()
                
                # Use the 'Command' structure for managing one2many and many2many fields
                # Command.clear() or (5, 0, 0) - Deletes all existing records
                # Command.create() or (0, 0, {values}) - Creates a new record
                matches_to_create = []
                for match in data.get('top_matches', []):
                    matches_to_create.append((0, 0, {
                        'filename': match['filename'],
                        'similarity': match['similarity'],
                        'match_id': match['id'],
                    }))

                # # This replaces all existing match_ids with the new ones
                record.match_ids = [(5, 0, 0)] + matches_to_create

            except requests.exceptions.RequestException as e:
                raise UserError(f"Network error during comparison: {str(e)}")
            except Exception as e:
                raise UserError(f"An unexpected error occurred: {str(e)}")

    def compare_button_modified(self):
        """
        Sends multiple images to the comparison API and processes the results.
        """
        for record in self:
            if not record.image:
                raise UserError("Please upload at least one image to compare.")

            # 1. Prepare a list of files for the multipart request.
            # The API expects the files under a key named 'images'.
            files_to_send = []
            for attachment in record.image:
                image_binary = base64.b64decode(attachment.datas)
                # Each file is a tuple: ('field_name', (filename, file_data, content_type))
                files_to_send.append(
                    ('images', (attachment.name, image_binary, attachment.mimetype))
                )

            try:
                # 2. Call the new API endpoint for multiple images.
                api_url = 'http://localhost:5001/compare/multiple'
                response = requests.post(api_url, files=files_to_send)
                response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
                
                data = response.json()
                print("data: ", data)
                matches_to_create = []

                for match in data.get('top_matches', []):
                    filename = match.get('filename')
                    similarity_score = match.get('combined_score') 
                    match_id = match.get('id')

                    # Check if any of the essential values are missing
                    if not all([filename, similarity_score is not None, match_id]):
                        print(f"Skipping incomplete match result: {match}")
                        continue

                    matches_to_create.append((0, 0, {
                        'filename': filename,
                        'similarity': similarity_score,
                        'match_id': match_id,
                    }))

                record.match_ids = [(5, 0, 0)] + matches_to_create

            except requests.exceptions.RequestException as e:
                # Handle network-related errors
                raise UserError(f"Network error during comparison: {str(e)}")
            except Exception as e:
                # Handle other potential errors (e.g., JSON decoding)
                raise UserError(f"An unexpected error occurred: {str(e)}")

# ... (ProductTemplate class remains the same) ...
class ProductTemplate(models.Model):
    _inherit = 'product.template'

    covering_material = fields.Char(string='Covering Material', tracking=True)
    dimensions = fields.Char(string='Dimensions', tracking=True)
    other_remarks = fields.Text(string='Other Remarks', tracking=True)