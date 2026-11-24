import os, re, secrets, uuid
import smtplib
from email.message import EmailMessage
from functools import wraps
from pathlib import Path
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
try:
    import stripe
except ImportError:
    stripe = None
def load_local_env():
    env_file=Path(__file__).with_name('.env')
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line=line.strip()
            if line and not line.startswith('#') and '=' in line:
                key,value=line.split('=',1); os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))
load_local_env()
from config import Config
from models import db, User, Category, Product, CartItem, WishlistItem, Order, OrderItem, Review, Payment, Coupon, ContactMessage
app = Flask(__name__); app.config.from_object(Config); db.init_app(app)
if stripe:
    stripe.api_key = app.config['STRIPE_SECRET_KEY']
def stripe_ready(): return bool(stripe and app.config['STRIPE_SECRET_KEY'].startswith('sk_test_'))
def csrf_token():
    if '_csrf' not in session: session['_csrf']=secrets.token_urlsafe(32)
    return session['_csrf']
app.jinja_env.globals['csrf_token']=csrf_token
@app.before_request
def protect_forms():
    if request.method=='POST':
        supplied=request.form.get('csrf_token','')
        if not supplied or not secrets.compare_digest(supplied,session.get('_csrf','')): abort(400)
def me(): return db.session.get(User, session.get('user_id')) if session.get('user_id') else None
@app.context_processor
def globals_for_templates():
    u=me(); cart_items=CartItem.query.filter_by(user_id=u.id).all() if u else []
    subtotal=sum(i.product.sale_price*i.quantity for i in cart_items); shipping=0 if subtotal>=2500 else (99 if subtotal else 0)
    return {'current_user':u,'cart_count':sum(i.quantity for i in cart_items),'cart_subtotal':subtotal,'cart_shipping':shipping,'cart_total':subtotal+shipping,'site_categories':Category.query.order_by(Category.name).all(),'contact_email':app.config['CONTACT_EMAIL'],'stripe_enabled':stripe_ready()}
def login_required(f):
    @wraps(f)
    def w(*a,**k):
        if not me(): flash('Please sign in to continue.','info'); return redirect(url_for('login'))
        return f(*a,**k)
    return w
def admin_required(f):
    @wraps(f)
    def w(*a,**k):
        if not me() or not me().is_admin: abort(403)
        return f(*a,**k)
    return w
def slug(s): return re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-') or secrets.token_hex(4)
def back_or(endpoint):
    ref=request.referrer or ''
    return ref if ref.startswith(request.host_url) else url_for(endpoint)
def valid_image(file, extension):
    signature=file.stream.read(12)
    file.stream.seek(0)
    if extension in {'jpg','jpeg'}: return signature.startswith(b'\xff\xd8\xff')
    if extension=='png': return signature.startswith(b'\x89PNG\r\n\x1a\n')
    if extension=='webp': return signature.startswith(b'RIFF') and signature[8:12]==b'WEBP'
    return False
def seed():
    if not Category.query.first():
        names=['Electronics','Fashion','Mobile Phones','Computers','Home & Living','Books','Beauty','Accessories']; cats={n:Category(name=n,slug=slug(n)) for n in names}; db.session.add_all(cats.values()); db.session.flush()
        demo=[('Studio Wireless Headphones','Electronics',6499,18,'Rich, balanced sound and all-day comfort with 40-hour battery.','🎧',1),('Everyday Canvas Backpack','Fashion',2299,0,'A water-resistant everyday carry with a padded laptop sleeve.','🎒',1),('Aero Smartwatch S2','Electronics',8999,12,'Bright AMOLED display, health sensors and a week of battery life.','⌚',1),('Ceramic Pour-over Set','Home & Living',1899,10,'A handmade ceramic dripper and matching cup for a slower morning.','☕',0),('Mechanical Keyboard 84','Computers',7499,15,'Compact hot-swappable keyboard with tactile switches and warm backlighting.','⌨️',1),('Botanical Skin Essentials','Beauty',1599,0,'A gentle daily ritual with plant-derived ingredients.','🌿',0),('Pocket E-reader 6 inch','Electronics',10999,8,'Glare-free reading screen, warm light and weeks of battery.','📖',0),('Classic Leather Wallet','Accessories',2799,0,'Slim responsibly made leather with room for the essentials.','👛',0)]
        for n,c,p,d,desc,emoji,feat in demo: db.session.add(Product(name=n,slug=slug(n),category=cats[c],price=p,discount=d,stock=25,description=desc,featured=bool(feat)))
    email=app.config['ADMIN_EMAIL']
    u=User.query.filter_by(email=email).first()
    if not u:
        u=User(name='DreamCart Admin',email=email,is_admin=True); u.set_password(app.config['ADMIN_PASSWORD']); db.session.add(u)
    u.is_admin=True
    if not Coupon.query.filter_by(code='WELCOME10').first(): db.session.add(Coupon(code='WELCOME10',percent=10))
    db.session.commit()

@app.cli.command('reset-admin-password')
def reset_admin_password():
    user=User.query.filter_by(email=app.config['ADMIN_EMAIL']).first()
    if not user:
        user=User(name='DreamCart Admin',email=app.config['ADMIN_EMAIL'],is_admin=True); db.session.add(user)
    user.is_admin=True; user.set_password(app.config['ADMIN_PASSWORD']); db.session.commit()
    print(f"Admin password updated for {user.email}.")

@app.route('/')
def index(): return render_template('index.html',featured=Product.query.filter_by(featured=True).limit(4).all(),newest=Product.query.order_by(Product.created_at.desc()).limit(4).all())
@app.route('/products')
def products():
    q=Product.query; term=request.args.get('q','').strip(); cat=request.args.get('category','')
    if term: q=q.join(Category).filter(Product.name.ilike(f'%{term}%')|Product.description.ilike(f'%{term}%')|Category.name.ilike(f'%{term}%'))
    if cat:
        c=Category.query.filter_by(slug=cat).first(); q=q.filter_by(category_id=c.id) if c else q.filter_by(id=-1)
    if request.args.get('min','').replace('.','',1).isdigit(): q=q.filter(Product.price*(100-Product.discount)/100>=float(request.args['min']))
    if request.args.get('max','').replace('.','',1).isdigit(): q=q.filter(Product.price*(100-Product.discount)/100<=float(request.args['max']))
    min_rating=request.args.get('rating',type=int); rating_applied=False
    if min_rating in range(1,6):
        q=q.outerjoin(Review).group_by(Product.id).having(db.func.avg(Review.rating)>=min_rating); rating_applied=True
    sortby=request.args.get('sort','popular')
    if sortby=='price_low': q=q.order_by(Product.price.asc())
    elif sortby=='price_high': q=q.order_by(Product.price.desc())
    elif sortby=='newest': q=q.order_by(Product.created_at.desc())
    elif sortby=='rating':
        if not rating_applied: q=q.outerjoin(Review).group_by(Product.id)
        q=q.order_by(db.func.avg(Review.rating).desc())
    else: q=q.order_by(Product.popularity.desc(),Product.featured.desc(),Product.created_at.desc())
    return render_template('products.html',products=q.all(),term=term,selected_category=cat,sort=sortby)
@app.route('/product/<slug>')
def product_detail(slug):
    p=Product.query.filter_by(slug=slug).first_or_404(); return render_template('product_detail.html',product=p,related=Product.query.filter(Product.category_id==p.category_id,Product.id!=p.id).limit(4).all())
@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
        if len(name)<2 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email) or len(password)<8: flash('Enter your name, a valid email and a password of at least 8 characters.','error')
        elif User.query.filter_by(email=email).first(): flash('An account already uses that email.','error')
        else:
            u=User(name=name,email=email,phone=request.form.get('phone','')); u.set_password(password); db.session.add(u); db.session.commit(); session['user_id']=u.id; return redirect(url_for('index'))
    return render_template('auth.html',mode='register')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=User.query.filter_by(email=request.form.get('email','').strip().lower()).first()
        if u and u.check_password(request.form.get('password','')): session.clear(); session['user_id']=u.id; return redirect(url_for('admin_dashboard' if u.is_admin else 'index'))
        flash('Email or password was not recognized.','error')
    return render_template('auth.html',mode='login')

@app.route('/forgot-password',methods=['GET','POST'])
def forgot_password():
    if request.method=='POST':
        email=request.form.get('email','').strip().lower(); user=User.query.filter_by(email=email,is_admin=False).first()
        if user and app.config['MAIL_SERVER'] and app.config['MAIL_FROM']:
            token=URLSafeTimedSerializer(app.config['SECRET_KEY']).dumps(user.id,salt='dreamcart-password-reset')
            link=url_for('reset_password',token=token,_external=True)
            message=EmailMessage(); message['Subject']='Reset your DreamCart password'; message['From']=app.config['MAIL_FROM']; message['To']=user.email
            message.set_content(f'Use this link to choose a new DreamCart password. It expires in one hour.\n\n{link}\n\nIf you did not request a reset, you can ignore this email.')
            try:
                with smtplib.SMTP(app.config['MAIL_SERVER'],app.config['MAIL_PORT'],timeout=10) as smtp:
                    if app.config['MAIL_USE_TLS']: smtp.starttls()
                    if app.config['MAIL_USERNAME']: smtp.login(app.config['MAIL_USERNAME'],app.config['MAIL_PASSWORD'])
                    smtp.send_message(message)
            except (OSError,smtplib.SMTPException):
                app.logger.exception('Password reset email delivery failed')
        flash('If the account exists and email delivery is configured, a password reset link has been sent.','info')
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>',methods=['GET','POST'])
def reset_password(token):
    try: user_id=URLSafeTimedSerializer(app.config['SECRET_KEY']).loads(token,salt='dreamcart-password-reset',max_age=3600)
    except (BadSignature,SignatureExpired): abort(400,'This password reset link is invalid or expired.')
    user=db.session.get(User,user_id)
    if not user or user.is_admin: abort(400,'This password reset link is invalid or expired.')
    if request.method=='POST':
        password=request.form.get('password','')
        if len(password)<8: flash('Use at least 8 characters for your new password.','error')
        elif password!=request.form.get('confirm_password',''): flash('The passwords do not match.','error')
        else:
            user.set_password(password); db.session.commit(); flash('Your password has been updated. Please sign in.','success'); return redirect(url_for('login'))
    return render_template('reset_password.html')
@app.route('/logout',methods=['POST'])
def logout(): session.clear(); return redirect(url_for('index'))
@app.route('/account',methods=['GET','POST'])
@login_required
def account():
    u=me()
    if request.method=='POST':
        if len(request.form.get('name','').strip())<2 or not request.form.get('address','').strip(): flash('Name and delivery address are required.','error')
        else:
            u.name=request.form['name'].strip(); u.phone=request.form.get('phone','').strip(); u.address=request.form['address'].strip()
            new_password=request.form.get('new_password','')
            if new_password:
                if not u.check_password(request.form.get('current_password','')): flash('Current password did not match; your profile details were saved, but the password was unchanged.','error')
                elif len(new_password)<8: flash('Your new password needs at least 8 characters.','error')
                else: u.set_password(new_password); flash('Your profile and password are updated.','success')
            else: flash('Your details are saved.','success')
            db.session.commit()
    return render_template('account.html',orders=Order.query.filter_by(user_id=u.id).order_by(Order.created_at.desc()).all())
@app.route('/cart')
@login_required
def cart(): return render_template('cart.html',items=CartItem.query.filter_by(user_id=me().id).all())
@app.route('/cart/add/<int:pid>',methods=['POST'])
@login_required
def cart_add(pid):
    p=Product.query.get_or_404(pid); qty=max(1,request.form.get('quantity',1,type=int) or 1); i=CartItem.query.filter_by(user_id=me().id,product_id=pid).first()
    if p.stock<1: flash('This item is out of stock.','error')
    else:
        if i: i.quantity=min(p.stock,i.quantity+qty)
        else: db.session.add(CartItem(user_id=me().id,product_id=pid,quantity=min(p.stock,qty)))
        db.session.commit(); flash('Added to your bag.','success')
    return redirect(back_or('cart'))
@app.route('/cart/update/<int:iid>',methods=['POST'])
@login_required
def cart_update(iid):
    i=CartItem.query.filter_by(id=iid,user_id=me().id).first_or_404(); q=request.form.get('quantity',1,type=int)
    if q<=0: db.session.delete(i)
    elif q<=i.product.stock: i.quantity=q
    else: flash(f'Only {i.product.stock} available.','error')
    db.session.commit(); return redirect(url_for('cart'))
@app.route('/cart/remove/<int:iid>',methods=['POST'])
@login_required
def cart_remove(iid):
    db.session.delete(CartItem.query.filter_by(id=iid,user_id=me().id).first_or_404()); db.session.commit(); return redirect(url_for('cart'))
@app.route('/wishlist')
@login_required
def wishlist(): return render_template('wishlist.html',items=WishlistItem.query.filter_by(user_id=me().id).all())
@app.route('/wishlist/toggle/<int:pid>',methods=['POST'])
@login_required
def wishlist_toggle(pid):
    Product.query.get_or_404(pid); i=WishlistItem.query.filter_by(user_id=me().id,product_id=pid).first()
    if i: db.session.delete(i)
    else: db.session.add(WishlistItem(user_id=me().id,product_id=pid))
    db.session.commit(); return redirect(back_or('wishlist'))
@app.route('/checkout',methods=['GET','POST'])
@login_required
def checkout():
    u=me(); items=CartItem.query.filter_by(user_id=u.id).all()
    if not items: flash('Your bag is empty.','info'); return redirect(url_for('products'))
    subtotal=sum(i.product.sale_price*i.quantity for i in items); shipping=0 if subtotal>=2500 else 99
    if request.method=='POST':
        address=request.form.get('address','').strip(); code=request.form.get('coupon','').strip().upper(); coupon=Coupon.query.filter_by(code=code,active=True).first() if code else None; method=request.form.get('payment_method','cod')
        if method not in ('cod','stripe'): flash('Choose a valid payment method.','error')
        elif not address: flash('Add a delivery address.','error')
        elif code and not coupon: flash('That coupon code is not valid or active.','error')
        elif any(i.quantity>i.product.stock for i in items): flash('Stock changed. Please update your bag.','error')
        else:
            discount=round(subtotal*coupon.percent/100,2) if coupon else 0
            total=round(subtotal+shipping-discount,2)
            if method=='stripe':
                if not stripe_ready():
                    flash('Card checkout is not configured. Add Stripe test keys to .env or choose cash on delivery.','error')
                else:
                    session['pending_checkout']={'address':address,'coupon':code,'items':{str(i.id):i.quantity for i in items}}
                    checkout_session=stripe.checkout.Session.create(mode='payment',payment_method_types=['card'],line_items=[{'price_data':{'currency':'inr','product_data':{'name':f'DreamCart order ({sum(i.quantity for i in items)} items)'} ,'unit_amount':int(round(total*100))},'quantity':1}],success_url=url_for('stripe_success',_external=True)+'?session_id={CHECKOUT_SESSION_ID}',cancel_url=url_for('stripe_cancel',_external=True),metadata={'user_id':str(u.id)})
                    return redirect(checkout_session.url,code=303)
            else:
                o=place_order(u,items,address,coupon,provider='cod')
                return redirect(url_for('order_success',number=o.order_number))
    summary_code=request.form.get('coupon','').strip().upper() if request.method=='POST' else ''
    summary_coupon=Coupon.query.filter_by(code=summary_code,active=True).first() if summary_code else None
    discount=round(subtotal*summary_coupon.percent/100,2) if summary_coupon else 0
    total=round(subtotal+shipping-discount,2)
    return render_template('checkout.html',items=items,subtotal=subtotal,shipping=shipping,discount=discount,total=total,coupon_code=summary_code)


def place_order(user,items,address,coupon=None,provider='cod',transaction_id=''):
    subtotal=sum(i.product.sale_price*i.quantity for i in items); shipping=0 if subtotal>=2500 else 99
    discount=round(subtotal*coupon.percent/100,2) if coupon else 0
    paid=provider=='stripe'
    order=Order(order_number=('DC-' if paid else 'CP-')+uuid.uuid4().hex[:10].upper(),user_id=user.id,total=round(subtotal+shipping-discount,2),shipping=shipping,address=address,payment_method='Stripe card' if paid else 'Cash on delivery',payment_status='Paid' if paid else 'Pending')
    db.session.add(order); db.session.flush()
    for item in items:
        db.session.add(OrderItem(order_id=order.id,product_id=item.product_id,name=item.product.name,price=item.product.sale_price,quantity=item.quantity))
        item.product.stock-=item.quantity; item.product.popularity+=item.quantity; db.session.delete(item)
    db.session.add(Payment(order_id=order.id,provider=provider,transaction_id=transaction_id,status='Paid' if paid else 'Pending'))
    user.address=address; db.session.commit()
    return order


@app.get('/payment/stripe/success')
@login_required
def stripe_success():
    sid=request.args.get('session_id',''); pending=session.get('pending_checkout')
    if not sid or not pending or not stripe_ready(): abort(400)
    existing=Payment.query.filter_by(provider='stripe',transaction_id=sid).first()
    if existing: return redirect(url_for('order_success',number=existing.order.order_number))
    paid_session=stripe.checkout.Session.retrieve(sid)
    if paid_session.payment_status!='paid' or paid_session.currency!='inr' or str(paid_session.metadata.get('user_id'))!=str(me().id): abort(403)
    items=CartItem.query.filter_by(user_id=me().id).all()
    expected={str(i.id):i.quantity for i in items}
    coupon=Coupon.query.filter_by(code=pending['coupon']).first() if pending.get('coupon') else None
    if expected!=pending.get('items') or any(i.quantity>i.product.stock for i in items) or (pending.get('coupon') and not coupon): abort(400)
    subtotal=sum(i.product.sale_price*i.quantity for i in items); shipping=0 if subtotal>=2500 else 99; discount=round(subtotal*coupon.percent/100,2) if coupon else 0
    if int(round((subtotal+shipping-discount)*100))!=paid_session.amount_total: abort(400)
    order=place_order(me(),items,pending['address'],coupon,provider='stripe',transaction_id=sid)
    session.pop('pending_checkout',None)
    return redirect(url_for('order_success',number=order.order_number))


@app.get('/payment/stripe/cancel')
@login_required
def stripe_cancel():
    session.pop('pending_checkout',None); flash('Card checkout was cancelled. Your bag is still saved.','info'); return redirect(url_for('checkout'))
@app.route('/order/<number>/success')
@login_required
def order_success(number): return render_template('order_success.html',order=Order.query.filter_by(order_number=number,user_id=me().id).first_or_404())
@app.route('/orders/<number>')
@login_required
def track_order(number):
    q=Order.query.filter_by(order_number=number)
    if not me().is_admin: q=q.filter_by(user_id=me().id)
    order=q.first_or_404()
    my_orders=Order.query.filter_by(user_id=me().id).order_by(Order.created_at.desc()).all() if not me().is_admin else []
    return render_template('track_order.html',order=order,my_orders=my_orders)
@app.route('/orders/<number>/cancel',methods=['POST'])
@login_required
def cancel_order(number):
    o=Order.query.filter_by(order_number=number,user_id=me().id).first_or_404()
    if o.status in ('Order Placed','Processing'):
        o.status='Cancelled'
        for i in o.items:
            if i.product: i.product.stock+=i.quantity
        db.session.commit(); flash('Order cancelled.','success')
    else: flash('This order can no longer be cancelled.','error')
    return redirect(url_for('track_order',number=number))
@app.route('/product/<slug>/review',methods=['POST'])
@login_required
def review(slug):
    p=Product.query.filter_by(slug=slug).first_or_404(); rating=request.form.get('rating',type=int); body=request.form.get('body','').strip()
    if rating not in range(1,6) or len(body)<5: flash('Choose a rating and write a short review.','error')
    elif Review.query.filter_by(user_id=me().id,product_id=p.id).first(): flash('You already reviewed this item.','info')
    else: db.session.add(Review(user_id=me().id,product_id=p.id,rating=rating,body=body)); db.session.commit(); flash('Thank you for your review.','success')
    return redirect(url_for('product_detail',slug=slug)+'#reviews')

@app.route('/about')
def about(): return render_template('info.html',eyebrow='OUR STORY',title='A little about us',body='DreamCart brings together useful, well-made things for everyday life. Find thoughtful products, clear prices and a smooth shopping experience.')
@app.route('/privacy')
def privacy(): return render_template('info.html',eyebrow='PRIVACY',title='Privacy, plainly put',body='We use the details you provide to manage your account, fulfill orders and answer support requests. Passwords are stored as secure hashes. This demo stores data locally in SQLite and does not share it with advertising partners.')
@app.route('/terms')
def terms(): return render_template('info.html',eyebrow='TERMS',title='The details',body='Orders are subject to product availability. Prices and shipping charges are shown before you place an order. This educational demo uses local checkout and does not process real payments.')
@app.route('/contact',methods=['GET','POST'])
def contact():
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip(); message=request.form.get('message','').strip()
        if len(name)<2 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email) or len(message)<10: flash('Please add your name, a valid email and a message of at least 10 characters.','error')
        else: db.session.add(ContactMessage(name=name,email=email,message=message)); db.session.commit(); flash('Your note is saved. Email delivery is not connected in this local demo.','success')
    return render_template('contact.html')

@app.route('/admin')
@admin_required
def admin_dashboard(): return render_template('admin/dashboard.html',customers=User.query.filter_by(is_admin=False).count(),products=Product.query.count(),orders=Order.query.count(),sales=db.session.query(db.func.sum(Order.total)).filter(Order.status!='Cancelled').scalar() or 0,recent=Order.query.order_by(Order.created_at.desc()).limit(8).all())
@app.route('/admin/products')
@admin_required
def admin_products(): return render_template('admin/products.html',products=Product.query.order_by(Product.created_at.desc()).all())
@app.route('/admin/products/new',methods=['GET','POST'])
@admin_required
def admin_new(): return product_editor()
@app.route('/admin/products/<int:pid>/edit',methods=['GET','POST'])
@admin_required
def admin_edit(pid): return product_editor(Product.query.get_or_404(pid))
def product_editor(p=None):
    if request.method=='POST':
        name=request.form.get('name','').strip(); price=request.form.get('price',type=float); cat=Category.query.get(request.form.get('category_id',type=int)); stock=request.form.get('stock',type=int); discount=request.form.get('discount',0,type=int)
        if not name or not price or price<=0 or not cat or stock is None or stock<0: flash('Enter valid product details.','error')
        else:
            if not p: p=Product(name=name,slug=slug(name)+'-'+secrets.token_hex(2),price=price,category=cat,stock=stock,description=''); db.session.add(p)
            p.name=name; p.price=price; p.category=cat; p.stock=stock; p.discount=min(90,max(0,discount)); p.description=request.form.get('description','').strip(); p.featured=bool(request.form.get('featured'))
            f=request.files.get('image')
            if f and f.filename:
                ext=f.filename.rsplit('.',1)[-1].lower()
                if ext not in {'png','jpg','jpeg','webp'} or not valid_image(f,ext): flash('Upload a valid PNG, JPG or WebP image.','error'); return render_template('admin/product_form.html',product=p,categories=Category.query.all())
                filename=secrets.token_hex(12)+'.'+ext; Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True,exist_ok=True); f.save(Path(app.config['UPLOAD_FOLDER'])/filename); p.image='uploads/'+filename
            db.session.commit(); flash('Product saved.','success'); return redirect(url_for('admin_products'))
    return render_template('admin/product_form.html',product=p,categories=Category.query.all())
@app.route('/admin/products/<int:pid>/delete',methods=['POST'])
@admin_required
def admin_delete(pid):
    p=Product.query.get_or_404(pid)
    if OrderItem.query.filter_by(product_id=pid).first(): p.stock=0; flash('Product has order history and was set out of stock.','info')
    else:
        Review.query.filter_by(product_id=pid).delete(); CartItem.query.filter_by(product_id=pid).delete(); WishlistItem.query.filter_by(product_id=pid).delete(); db.session.delete(p); flash('Product deleted.','success')
    db.session.commit(); return redirect(url_for('admin_products'))
@app.route('/admin/orders')
@admin_required
def admin_orders(): return render_template('admin/orders.html',orders=Order.query.order_by(Order.created_at.desc()).all())
@app.route('/admin/orders/<int:oid>/status',methods=['POST'])
@admin_required
def admin_status(oid):
    o=Order.query.get_or_404(oid); status=request.form.get('status')
    valid_statuses=('Order Placed','Processing','Shipped','Out for Delivery','Delivered','Cancelled')
    if status not in valid_statuses:
        flash('Choose a valid order status.','error')
    elif o.status=='Cancelled' and status!='Cancelled':
        flash('Cancelled orders cannot be reopened.','error')
    elif status=='Cancelled' and o.status not in ('Order Placed','Processing','Cancelled'):
        flash('Only new or processing orders can be cancelled.','error')
    elif status!=o.status:
        if status=='Cancelled':
            for item in o.items:
                if item.product: item.product.stock+=item.quantity
        o.status=status; db.session.commit(); flash('Order status updated.','success')
    return redirect(url_for('admin_orders'))
@app.route('/admin/customers')
@admin_required
def admin_customers(): return render_template('admin/customers.html',users=User.query.filter_by(is_admin=False).order_by(User.created_at.desc()).all())
@app.route('/admin/messages')
@admin_required
def admin_messages(): return render_template('admin/messages.html',messages=ContactMessage.query.order_by(ContactMessage.created_at.desc()).all())
@app.route('/admin/reviews')
@admin_required
def admin_reviews(): return render_template('admin/reviews.html',reviews=Review.query.order_by(Review.created_at.desc()).all())
@app.route('/admin/reviews/<int:rid>/delete',methods=['POST'])
@admin_required
def admin_review_delete(rid):
    db.session.delete(Review.query.get_or_404(rid)); db.session.commit(); flash('Review removed.','success'); return redirect(url_for('admin_reviews'))
@app.route('/admin/categories',methods=['GET','POST'])
@admin_required
def admin_categories():
    if request.method=='POST':
        name=request.form.get('name','').strip()
        if len(name)<2: flash('Category name must have at least two characters.','error')
        elif Category.query.filter_by(name=name).first(): flash('That category already exists.','error')
        else: db.session.add(Category(name=name,slug=slug(name)+'-'+secrets.token_hex(2))); db.session.commit(); flash('Category added.','success')
    return render_template('admin/categories.html',categories=Category.query.order_by(Category.name).all())
@app.route('/admin/categories/<int:cid>/delete',methods=['POST'])
@admin_required
def admin_category_delete(cid):
    c=Category.query.get_or_404(cid)
    if c.products: flash('Move or remove this category’s products before deleting it.','error')
    else: db.session.delete(c); db.session.commit(); flash('Category deleted.','success')
    return redirect(url_for('admin_categories'))
@app.route('/admin/coupons',methods=['GET','POST'])
@admin_required
def admin_coupons():
    if request.method=='POST':
        code=request.form.get('code','').strip().upper(); percent=request.form.get('percent',type=int)
        if not code or percent not in range(1,91): flash('Enter a coupon code and a discount from 1 to 90%.','error')
        elif Coupon.query.filter_by(code=code).first(): flash('That coupon already exists.','error')
        else: db.session.add(Coupon(code=code,percent=percent)); db.session.commit(); flash('Coupon created.','success')
    return render_template('admin/coupons.html',coupons=Coupon.query.order_by(Coupon.code).all())
@app.route('/admin/coupons/<int:cid>/toggle',methods=['POST'])
@admin_required
def admin_coupon_toggle(cid):
    c=Coupon.query.get_or_404(cid); c.active=not c.active; db.session.commit(); flash('Coupon updated.','success'); return redirect(url_for('admin_coupons'))
@app.errorhandler(403)
def forbidden(e): return render_template('info.html',eyebrow='403',title='Access restricted',body='This area is for store administrators. Sign in with an admin account to continue.'),403
with app.app_context():
    Path(app.instance_path).mkdir(parents=True,exist_ok=True); Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True,exist_ok=True); db.create_all(); seed()
if __name__=='__main__': app.run(debug=os.getenv('FLASK_DEBUG','false').lower()=='true')
