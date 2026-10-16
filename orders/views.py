import io
import json
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from django.http import (
    FileResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from PIL import Image, ImageDraw

from .models import CommissionOrder, VectorJob
from .services.vectorizer import process_uploaded_photo


def _generate_demo_portrait() -> io.BytesIO:
    """
    Loads a close-up portrait photograph (`skimage.data.astronaut`) so `rembg`
    segments the person naturally and demonstrates photographic fine-line engraving.
    """
    from skimage import data as skdata

    raw_rgb = skdata.astronaut()[5:380, 90:420]
    img = Image.fromarray(raw_rgb, mode='RGB')

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    buf.name = 'sample_portrait_photo.png'
    return buf


def _inject_custom_text_into_svg(svg_path, custom_text: str):
    """Updates or inserts the custom text inside Layer_02_Solid_Fills of the private SVG."""
    if not svg_path.is_file():
        return
    clean_text = custom_text.strip().upper()[:40]
    if not clean_text:
        return
    content = svg_path.read_text(encoding='utf-8')
    escaped = escape(clean_text)
    text_el = (
        f'    <text x="360" y="678" text-anchor="middle" '
        f'font-family="Arial, sans-serif" font-weight="bold" font-size="28" '
        f'letter-spacing="2">{escaped}</text>\n  </g>'
    )
    if '<text ' in content:
        import re

        content = re.sub(
            r'\s*<text [^>]*>.*?</text>\s*</g>',
            f'\n{text_el}',
            content,
            count=1,
            flags=re.DOTALL,
        )
    else:
        content = content.replace('  </g>\n</svg>', f'{text_el}\n</svg>')
    svg_path.write_text(content, encoding='utf-8')


def home(request):
    return render(request, 'index.html')


def vectorizer_studio(request):
    return render(request, 'vectorizer.html')


def street_signs(request):
    return render(request, 'street_signs.html')


@require_POST
def process_preview_api(request):
    """
    POST /api/process-preview/
    Accepts an uploaded image (or `use_sample=1`), removes background,
    posterizes into 3 LightBurn vector layers (#000000 Cut, #0000FF Score, #FF0000 Fill),
    stores the clean SVG strictly in settings.PRIVATE_SVG_ROOT, and returns
    watermarked composite raster previews for Slate, MDF/Birch, and Edge-Lit Acrylic.
    """
    custom_text = (request.POST.get('custom_text') or '').strip()[:40]
    use_sample = request.POST.get('use_sample') == '1'
    uploaded_file = request.FILES.get('image')

    if not uploaded_file and not use_sample:
        return JsonResponse(
            {'ok': False, 'error': 'Please upload a photo (JPG, PNG, or WEBP) or try the sample image.'},
            status=400,
        )

    if uploaded_file:
        if uploaded_file.size > 12 * 1024 * 1024:
            return JsonResponse(
                {'ok': False, 'error': 'Image file is too large (maximum 12MB).'},
                status=400,
            )
        source_file = uploaded_file
        original_name = uploaded_file.name
    else:
        source_file = _generate_demo_portrait()
        original_name = 'brummie_portrait_sample.png'

    try:
        job_uuid, svg_filename, previews = process_uploaded_photo(
            source_file, custom_text=custom_text
        )
    except Exception as exc:
        return JsonResponse(
            {'ok': False, 'error': f'Unable to process image: {exc}'},
            status=400,
        )

    job = VectorJob.objects.create(
        job_id=job_uuid,
        original_filename=original_name,
        private_svg_filename=svg_filename,
        custom_text=custom_text,
        selected_material=request.POST.get('material', 'slate'),
    )
    request.session['last_vector_job_id'] = str(job.job_id)

    return JsonResponse(
        {
            'ok': True,
            'job_id': str(job.job_id),
            'previews': previews,
            'layers': [
                {'code': '00', 'name': 'Cut Profile', 'hex': '#000000', 'stroke': '0.1mm'},
                {'code': '01', 'name': 'Line / Score Accent', 'hex': '#0000FF', 'stroke': '0.1mm'},
                {'code': '02', 'name': 'Solid Engraving Fills', 'hex': '#FF0000', 'fill': 'Solid'},
            ],
        }
    )


@require_POST
def submit_order_api(request):
    """
    POST /api/submit-order/
    Saves a physical engraving order or custom commission request into the admin
    dashboard and links the server-side clean LightBurn SVG when present.
    """
    try:
        data = (
            json.loads(request.body.decode('utf-8'))
            if request.content_type == 'application/json'
            else request.POST
        )
    except Exception:
        return HttpResponseBadRequest('Invalid payload')

    customer_name = (data.get('customer_name') or '').strip()
    customer_email = (data.get('customer_email') or '').strip()
    if not customer_name or not customer_email:
        return JsonResponse(
            {'ok': False, 'error': 'Please provide your name and email address so Paul can send your PayPal link.'},
            status=400,
        )

    job_id = (data.get('job_id') or request.session.get('last_vector_job_id') or '').strip()
    custom_text = (data.get('custom_text') or '').strip()[:120]
    material = (data.get('material') or 'Natural Slate Coaster').strip()
    size_option = (data.get('size_option') or '100x100mm Single Coaster (£12.00)').strip()
    finish_option = (data.get('finish_option') or '').strip()
    fulfillment_type = (data.get('fulfillment_type') or 'uk_delivery').strip()
    product_category = (data.get('product_category') or 'photo_engraving').strip()

    try:
        estimated_price = float(data.get('estimated_price') or 12.00)
    except (TypeError, ValueError):
        estimated_price = 12.00

    try:
        quantity = max(1, int(data.get('quantity') or 1))
    except (TypeError, ValueError):
        quantity = 1

    vector_job = None
    if job_id:
        vector_job = VectorJob.objects.filter(job_id=job_id).first()
        if vector_job and custom_text:
            vector_job.custom_text = custom_text[:80]
            vector_job.save(update_fields=['custom_text'])
            _inject_custom_text_into_svg(vector_job.get_svg_path(), custom_text)

    order = CommissionOrder.objects.create(
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=(data.get('customer_phone') or '').strip(),
        product_category=product_category,
        material=material,
        size_option=size_option,
        finish_option=finish_option,
        custom_text=custom_text,
        quantity=quantity,
        fulfillment_type=fulfillment_type,
        delivery_address=(data.get('delivery_address') or '').strip(),
        notes=(data.get('notes') or '').strip(),
        estimated_price=estimated_price,
        vector_job=vector_job,
    )

    return JsonResponse(
        {
            'ok': True,
            'order_reference': order.order_reference,
            'message': (
                f"Order {order.order_reference} received! Paul has your design and LightBurn file "
                f"and will email a PayPal link to {order.customer_email} shortly."
            ),
        }
    )


@require_POST
def unlock_digital_svg_api(request):
    """
    POST /api/unlock-digital-svg/
    Processes the £4.99 Digital LightBurn SVG License purchase and issues a
    secure, expiring one-time download link for the raw .svg file.
    """
    try:
        data = (
            json.loads(request.body.decode('utf-8'))
            if request.content_type == 'application/json'
            else request.POST
        )
    except Exception:
        return HttpResponseBadRequest('Invalid payload')

    job_id = (data.get('job_id') or request.session.get('last_vector_job_id') or '').strip()
    customer_email = (data.get('customer_email') or '').strip()
    customer_name = (data.get('customer_name') or 'Digital License Buyer').strip()
    custom_text = (data.get('custom_text') or '').strip()[:80]

    if not job_id:
        return JsonResponse(
            {'ok': False, 'error': 'Please upload and vectorize a photo first.'},
            status=400,
        )

    job = get_object_or_404(VectorJob, job_id=job_id)
    if custom_text:
        job.custom_text = custom_text
        _inject_custom_text_into_svg(job.get_svg_path(), custom_text)
    if customer_email:
        job.customer_email = customer_email
    job.issue_one_time_token(hours_valid=24)

    # Also log the digital purchase in CommissionOrder for accounting
    order = CommissionOrder.objects.create(
        customer_name=customer_name,
        customer_email=customer_email or 'digital@paulybruv.local',
        product_category='digital_svg',
        material='LightBurn 3-Layer SVG Digital License',
        size_option='100mm x 100mm Vector Master (.svg)',
        custom_text=custom_text,
        fulfillment_type='digital_download',
        estimated_price=4.99,
        status='completed',
        paypal_link_sent=True,
        vector_job=job,
    )

    download_url = reverse('download_svg_once', kwargs={'token': job.download_token})
    return JsonResponse(
        {
            'ok': True,
            'order_reference': order.order_reference,
            'download_url': download_url,
            'expires_at': job.token_expires_at.isoformat() if job.token_expires_at else None,
        }
    )


@require_GET
def download_svg_once(request, token):
    """
    GET /api/download-svg/<uuid:token>/
    Streams the clean, production-ready LightBurn SVG once and immediately
    invalidates the one-time token so the link cannot be shared or reused.
    """
    job = get_object_or_404(VectorJob, download_token=token)
    if not job.is_token_valid():
        return HttpResponseForbidden(
            'This one-time LightBurn SVG download link has already been used or has expired.'
        )

    svg_path = job.get_svg_path()
    job.token_used = True
    job.save(update_fields=['token_used'])

    filename = f"pauly_bruv_lightburn_{str(job.job_id)[:8]}.svg"
    return FileResponse(
        open(svg_path, 'rb'),
        as_attachment=True,
        filename=filename,
        content_type='image/svg+xml',
    )
