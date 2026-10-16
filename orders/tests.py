import io
from django.test import TestCase
from django.urls import reverse
from PIL import Image, ImageDraw
from .models import CommissionOrder, VectorJob


class VectorizerAndOrderTests(TestCase):
    def _create_test_photo(self) -> io.BytesIO:
        img = Image.new('RGB', (320, 320), (245, 245, 245))
        draw = ImageDraw.Draw(img)
        # Subject silhouette + dark sunglasses fill
        draw.ellipse([70, 60, 250, 260], fill=(190, 195, 205), outline=(60, 65, 75), width=3)
        draw.rectangle([95, 110, 150, 145], fill=(15, 15, 20))
        draw.rectangle([170, 110, 225, 145], fill=(15, 15, 20))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        buf.name = 'test_customer.png'
        return buf

    def test_pages_render_200(self):
        for route in ['home', 'vectorizer', 'street_signs']:
            res = self.client.get(reverse(route))
            self.assertEqual(res.status_code, 200)

    def test_process_preview_generates_private_lightburn_svg_and_watermarked_proofs(self):
        photo = self._create_test_photo()
        res = self.client.post(
            reverse('process_preview_api'),
            {'image': photo, 'custom_text': 'KEEP RIGHT ON', 'material': 'slate'},
        )
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload['ok'])
        self.assertIn('job_id', payload)
        self.assertIn('slate', payload['previews'])
        self.assertIn('mdf', payload['previews'])
        self.assertIn('acrylic', payload['previews'])

        job = VectorJob.objects.get(job_id=payload['job_id'])
        svg_path = job.get_svg_path()
        self.assertTrue(svg_path.is_file())

        svg_text = svg_path.read_text(encoding='utf-8')
        # Verify LightBurn layer standards
        self.assertIn('id="Layer_00_Cut_Profile"', svg_text)
        self.assertIn('stroke="#000000"', svg_text)
        self.assertIn('stroke-width="0.1mm"', svg_text)
        self.assertIn('id="Layer_01_Line_Score"', svg_text)
        self.assertIn('stroke="#0000FF"', svg_text)
        self.assertIn('id="Layer_02_Solid_Fills"', svg_text)
        self.assertIn('fill="#FF0000"', svg_text)
        self.assertIn('KEEP RIGHT ON', svg_text)

    def test_physical_order_links_to_vector_job(self):
        res_preview = self.client.post(
            reverse('process_preview_api'),
            {'use_sample': '1', 'custom_text': 'BLUES 1875'},
        )
        job_id = res_preview.json()['job_id']

        res_order = self.client.post(
            reverse('submit_order_api'),
            {
                'job_id': job_id,
                'customer_name': 'Paul Test',
                'customer_email': 'paul@example.com',
                'material': 'Natural Slate Coaster',
                'size_option': 'Set of 4 Slate Coasters',
                'custom_text': 'ST ANDREWS B9',
                'fulfillment_type': 'birmingham_collection',
                'estimated_price': '32.00',
            },
        )
        self.assertEqual(res_order.status_code, 200)
        data = res_order.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['order_reference'].startswith('PBE-'))

        order = CommissionOrder.objects.get(order_reference=data['order_reference'])
        self.assertEqual(str(order.vector_job.job_id), job_id)
        self.assertIn(
            'ST ANDREWS B9',
            order.vector_job.get_svg_path().read_text(encoding='utf-8'),
        )

    def test_digital_svg_license_one_time_download_security(self):
        res_preview = self.client.post(
            reverse('process_preview_api'),
            {'use_sample': '1'},
        )
        job_id = res_preview.json()['job_id']

        # Unlock digital license
        res_unlock = self.client.post(
            reverse('unlock_digital_svg_api'),
            {
                'job_id': job_id,
                'customer_name': 'Maker Buyer',
                'customer_email': 'maker@example.com',
            },
        )
        self.assertEqual(res_unlock.status_code, 200)
        download_url = res_unlock.json()['download_url']

        # First download succeeds and returns raw SVG
        res_dl_1 = self.client.get(download_url)
        self.assertEqual(res_dl_1.status_code, 200)
        self.assertEqual(res_dl_1['Content-Type'], 'image/svg+xml')
        res_dl_1.close()

        # Second download with same token is forbidden (one-time link)
        res_dl_2 = self.client.get(download_url)
        self.assertEqual(res_dl_2.status_code, 403)
