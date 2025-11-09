from odoo import http
from odoo.http import request, route
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.fields import Command
from werkzeug.exceptions import NotFound
from urllib.parse import quote_plus

class CustomWebsiteSale(WebsiteSale):

    @http.route(['/shop/cart'], type='http', auth='public', website=True, sitemap=False)
    def cart(self, access_token=None, revive='', **post):
        """
        Overrides the original /shop/cart endpoint.
        Fetches the current cart (sale.order) and passes it to the custom template.
        """
        # Get the current sale order (cart) from the standard website utility
        # order = http.request.website.sale_get_order()
        
        # # Prepare the rendering values, including the order object
        # values = {
        #     'order': order,
        #     'suggested_products': [], # Optional: You can add suggestions here if needed
        #     'website_sale_order': order, # Use the standard key for compatibility
        # }
        
        # # Render the custom template, passing the cart data


        if not request.website.has_ecommerce_access():
            return request.redirect('/web/login')

        order = request.website.sale_get_order()
        if order and order.state != 'draft':
            request.session['sale_order_id'] = None
            order = request.website.sale_get_order()

        request.session['website_sale_cart_quantity'] = order.cart_quantity

        values = {}
        if access_token:
            abandoned_order = request.env['sale.order'].sudo().search([('access_token', '=', access_token)], limit=1)
            if not abandoned_order:  # wrong token (or SO has been deleted)
                raise NotFound()
            if abandoned_order.state != 'draft':  # abandoned cart already finished
                values.update({'abandoned_proceed': True})
            elif revive == 'squash' or (revive == 'merge' and not request.session.get('sale_order_id')):  # restore old cart or merge with unexistant
                request.session['sale_order_id'] = abandoned_order.id
                return request.redirect('/shop/cart')
            elif revive == 'merge':
                abandoned_order.order_line.write({'order_id': request.session['sale_order_id']})
                abandoned_order.action_cancel()
            elif abandoned_order.id != request.session.get('sale_order_id'):  # abandoned cart found, user have to choose what to do
                values.update({'access_token': abandoned_order.access_token})

        countries = request.env['res.country'].sudo().search([])
        values['countries'] = countries

        values.update({
            'website_sale_order': order,
            'date': fields.Date.today(),
            'suggested_products': [],
        })
        if order:
            order.order_line.filtered(lambda sol: sol.product_id and not sol.product_id.active).unlink()
            values['suggested_products'] = order._cart_accessories()
            values.update(self._get_express_shop_payment_values(order))

        values.update(self._cart_values(**post))    
        return http.request.render("website_custom_checkout.custom_cart_with_products", values)

    @http.route(['/custom_checkout/get_quote'], type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def custom_get_quote(self, **post):
        """
        Handle customer details form submission, create/find partner and create/update a sale.order (quotation).
        """
        # Required fields (only these must be provided)
        required = ['name', 'email', 'phone', 'cust_country', 'city', 'pincode']
        missing = [f for f in required if not post.get(f)]
        if missing:
            # simple feedback: redirect back with a query param (could be improved)
            return request.redirect('/shop/cart?quote_error=missing_fields')

        Partner = request.env['res.partner'].sudo()
        # Try to find existing partner by email, else create
        partner = None
        
        if not partner:
            vals = {
                'name': post.get('name'),
                'email': post.get('email'),
                'phone': post.get('phone'),
                'country_id': post.get('cust_country'),
                'state_id': post.get('state_id'),
                'city': post.get('city'),
                'zip': post.get('pincode'),
            }
            # prefer numeric ids (country_id/state_id) from select fields; otherwise fallback to name search
            # if post.get('country_id'):
            #     try:
            #         vals['country_id'] = int(post.get('country_id'))
            #     except Exception:
            #         vals['country_id'] = None
            # else:
            #     country = request.env['res.country'].sudo().search([('id', '=', post.get('cust_country') or '')], limit=1)
            #     if country:
            #         vals['country_id'] = country.id
            # print('country id:', vals['country_id'])
            # if post.get('state_id'):
            #     try:
            #         vals['state_id'] = int(post.get('state_id'))
            #     except Exception:
            #         vals['state_id'] = None
            # else:
            #     state = request.env['res.country.state'].sudo().search([('name', 'ilike', post.get('state') or '')], limit=1)
            #     if state:
            #         vals['state_id'] = state.id

            print('partner vals:', vals)
            partner = Partner.create(vals)

        # Build a new quotation (always create a new sale.order) and copy the
        # current cart lines into it (if any). This ensures each Get Quote
        # action generates its own quotation while the customer's cart is
        # emptied afterwards.
        SaleOrder = request.env['sale.order'].sudo()
        current_order = request.website.sale_get_order()

        # create the new quotation with partner info
        new_order_vals = {
            'partner_id': partner.id,
            'partner_invoice_id': partner.id,
            'partner_shipping_id': partner.id,
            'website_id': request.website.id,
        }
        new_order = SaleOrder.create(new_order_vals)

        # copy lines from current cart into the new quotation (copy preserves
        # product, description, qty, etc.). Use sudo to ensure permissions.
        try:
            if current_order and current_order.order_line:
                for line in current_order.order_line:
                    try:
                        line.sudo().copy({'order_id': new_order.id})
                    except Exception:
                        # ignore problems copying a specific line
                        continue
                
        except Exception:
            # ignore any non-fatal copy errors
            pass

        # attach a message on the new quotation
        new_order.sudo().message_post(body=f"Order created - {partner.name} ({partner.email})")
        new_order.action_confirm()
        # Empty the customer's current cart: remove lines from the session order
        # so the UI and session reflect an empty cart after redirect.
        try:
            if current_order:
                try:
                    if current_order.state not in ['draft', 'cancel']:
                        current_order.sudo().action_cancel()
                        current_order.sudo().write({'state': 'cancel'})
                    current_order.sudo().unlink()
                except Exception as e:
                    print(f"Failed to delete old cart: {e}")
            request.session['sale_order_id'] = None
            request.session['website_sale_cart_quantity'] = 0
        except Exception:
            # ignore any session-clearing issues
            pass

        # Redirect to cart with success flag and new order reference (escaped)
        order_ref = getattr(new_order, 'name', None) or ''
        try:
            order_ref_q = quote_plus(order_ref)
        except Exception:
            order_ref_q = ''
        return request.redirect(f'/shop/cart?quote_success=1&order_name={order_ref_q}')

    @http.route(['/custom_checkout/get_csrf'], type='json', auth='public', website=True)
    def get_csrf(self, **kw):
        """Return a fresh CSRF token for client-side forms.

        This helps avoid 'invalid CSRF token' errors when pages are cached or
        when the hidden token in a form becomes stale.
        """
        return {'csrf_token': request.csrf_token}

    @http.route(['/custom_checkout/remove_line'], type='http', auth='public', website=True)
    def remove_line(self, line_id=None, **kw):
        """Remove a sale.order.line from the current website cart if it belongs to it."""
        print('Hello from remove_line:', line_id)
        try:
            line_id = int(line_id)
        except Exception:
            return request.redirect('/shop/cart')

        SaleLine = request.env['sale.order.line'].sudo()
        line = SaleLine.search([('id', '=', line_id)], limit=1)
        if not line:
            return request.redirect('/shop/cart')

        # Only allow removing lines that belong to the current website draft order
        order = request.website.sale_get_order()
        if order and line.order_id and line.order_id.id == order.id:
            try:
                line.unlink()
            except Exception:
                # silent fail for now
                pass

        return request.redirect('/shop/cart')

    @http.route(['/custom_checkout/update_line_qty'], type='json', auth='public', website=True)
    def update_line_qty(self, line_id=None, quantity=None, **kw):
        """Update the quantity of a sale.order.line belonging to the current website cart.

        Expects JSON with: { line_id: int, quantity: int } where quantity is a delta (can be negative)
        Returns JSON: { success: bool, line_id: int, new_qty: float, cart_quantity: int }
        """
        # Read JSON body first (request.jsonrequest) for type='json' calls, fallback to kwargs
        data = None
        if getattr(request, 'jsonrequest', None):
            data = request.jsonrequest
        else:
            # sometimes fetch() doesn't populate jsonrequest for type='json', try raw body
            try:
                raw = request.httprequest.get_data(as_text=True)
                if raw:
                    import json
                    data = json.loads(raw)
                else:
                    data = kw
            except Exception:
                data = kw
        # Debug log payload (temporary)
        _logger = request.env['ir.logging'] if hasattr(request.env, 'ir') else None
        try:
            # we can't always write to ir.logging in some contexts; fallback to print
            print('update_line_qty payload:', data)
        except Exception:
            pass
        # prefer values from the JSON body
        print('data:', data)
        line_id = data.get('line_id', line_id)
        quantity = data.get('quantity', quantity)

        try:
            line_id = int(line_id)
        except Exception:
            return {'success': False, 'error': 'invalid_line_id'}

        # Support either a delta ('quantity') or an absolute set ('set_qty')
        delta = None
        set_qty = None
        if 'set_qty' in data:
            try:
                set_qty = int(data.get('set_qty'))
            except Exception:
                return {'success': False, 'error': 'invalid_set_quantity'}
        else:
            try:
                delta = int(quantity)
            except Exception:
                return {'success': False, 'error': 'invalid_quantity'}

        order = request.website.sale_get_order()
        if not order:
            return {'success': False, 'error': 'no_order'}

        SaleLine = request.env['sale.order.line'].sudo()
        line = SaleLine.search([('id', '=', line_id), ('order_id', '=', order.id)], limit=1)
        if not line:
            return {'success': False, 'error': 'line_not_found'}

        try:
            if set_qty is not None:
                # set absolute quantity
                new_qty = float(set_qty)
                if new_qty <= 0:
                    line.unlink()
                    new_qty = 0
                else:
                    line.sudo().write({'product_uom_qty': new_qty})
            else:
                # delta update
                new_qty = float(line.product_uom_qty) + (delta or 0)
                if new_qty <= 0:
                    line.unlink()
                    new_qty = 0
                else:
                    line.sudo().write({'product_uom_qty': new_qty})
        except Exception:
            return {'success': False, 'error': 'update_failed'}

        # refresh order (sudo to read cart qty)
        order = request.env['sale.order'].sudo().browse(order.id)
        return {
            'success': True,
            'line_id': line_id,
            'new_qty': new_qty,
            'cart_quantity': order.cart_quantity,
        }