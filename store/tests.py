from django.test import TestCase, override_settings


class ErrorPageTests(TestCase):
    @override_settings(DEBUG=False)
    def test_unknown_url_displays_custom_not_found_page(self):
        response = self.client.get('/this-page-does-not-exist/')

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Page Not Found', status_code=404)
