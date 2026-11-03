"""Real extension + Chromium against intercepted Google fixtures; no live reviews."""
import io
import json
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from app import create_app
from browser_bridge import open_normal_chrome

ROOT = Path(__file__).resolve().parents[1]
GOOGLE = '''<!doctype html><html><body><button aria-label="Google Account: Test (owner@example.com)">Account</button>
<h1>My Market</h1><button data-item-id="address" aria-label="Address: Main Road, Karachi">Main Road, Karachi</button><button onclick="document.querySelector('#writer').hidden=false">Write a review</button>
<div id="writer" role="dialog" hidden><h2>Rate and review</h2>{radios}<textarea></textarea>
<button id="post" onclick="window.posts++;document.querySelector('#result').textContent='Your review has been posted.';document.querySelector('#writer').hidden=true">Post</button></div>
<p id="result"></p><script>window.posts=0;function rate(button) {{document.querySelectorAll('[role=radio]').forEach(r=>r.setAttribute('aria-checked','false'));button.setAttribute('aria-checked','true');}}</script></body></html>'''
RADIOS = ''.join(f'<button role="radio" aria-label="{i} star{"s" if i>1 else ""}" aria-checked="false" onclick="rate(this)">{i}</button>' for i in range(1,6))
WIDGET_URL = 'https://www.google.com/maps/api/js/ReviewsService.LoadWriteWidget?hl=en&authuser=0&placeid=fixture123'
WIDGET_RADIOS = ''.join(f'<div role="radio" aria-label="{word} star{"s" if i>1 else ""}" data-rating="{i}" '
    f'aria-checked="false" onclick="rate(this)">{i}</div>'
    for i,word in enumerate(('One','Two','Three','Four','Five'),1))
WIDGET = '''<!doctype html><html><body><h2>My Market</h2>
<div role="radiogroup" aria-label="Rating stars">{radios}</div>
<h3>Food</h3><div role="radiogroup" aria-label="Food rating stars">{radios}</div>
<h3>Service</h3><div role="radiogroup" aria-label="Service rating stars">{radios}</div>
<textarea aria-label="Enter review"></textarea><button id="widget-post"
onclick="window.posts++;parent.postMessage({{type:'FIXTURE_POSTED'}},'*')">Post</button>
<script>window.posts=0;function rate(button){{button.closest('[role=radiogroup]').querySelectorAll('[role=radio]')
.forEach(r=>r.setAttribute('aria-checked','false'));button.setAttribute('aria-checked','true')}}</script></body></html>'''
SAVED_CARD = '''<div><h2>Your review</h2></div><div data-review-id="saved-fixture">
<span role="img" aria-label="4 stars"></span><span class="wiI7pd">My genuine visit.
The staff were helpful.</span></div><div aria-hidden="true"></div><div><button aria-label="Edit your review">Edit your review</button></div>'''


class NormalChromeApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(self.temp.name, config={"mode": "extension"})
        self.client = self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as state:
            self.headers = {'X-CSRF-Token':state['csrf']}
        self.worker = self.app.extensions['review_worker']

    def test_launch_uses_normal_chrome_without_automation_profile(self):
        with patch('browser_bridge.subprocess.Popen') as launch:
            open_normal_chrome('https://accounts.google.com/ServiceLogin')
        arguments = launch.call_args.args[0]
        self.assertEqual(arguments[1:], ['--new-tab','https://accounts.google.com/ServiceLogin'])
        self.assertFalse(any('debug' in arg or 'profile' in arg or 'AutomationControlled' in arg for arg in arguments))

    def test_expected_account_must_match(self):
        with patch('browser_bridge.open_normal_chrome'):
            response=self.client.post('/api/browser/login',json={'email':'owner@example.com'},headers=self.headers)
        self.assertEqual(response.status_code,202)
        self.assertEqual(self.client.post('/api/browser/verified',json={'email':'other@example.com'},headers=self.headers).status_code,409)
        self.assertEqual(self.client.post('/api/browser/verified',json={'email':'owner@example.com'},headers=self.headers).status_code,200)

    def test_zip_contains_only_extension_sources(self):
        response=self.client.get('/extension/download')
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            files=archive.namelist()
            self.assertIn('tasmee-chrome-extension/manifest.json',files)
            self.assertIn('tasmee-chrome-extension/review_widget.js',files)
            self.assertFalse(any('.env' in name or 'sqlite' in name or 'accounts.json' in name for name in files))
            manifest=json.loads(archive.read('tasmee-chrome-extension/manifest.json'))
            self.assertNotIn('cookies',manifest['permissions'])
            self.assertNotIn('proxy',manifest['permissions'])
            widget=next(script for script in manifest['content_scripts'] if 'review_widget.js' in script['js'])
            self.assertTrue(widget['all_frames'])
            self.assertTrue(all('/maps/api/js/ReviewsService.LoadWriteWidget' in match for match in widget['matches']))

    def make_review(self):
        self.client.post('/api/browser/verified',json={'email':'owner@example.com'},headers=self.headers)
        response=self.client.post('/api/reviews',headers=self.headers,json={
            'target':'https://www.google.com/maps/place/My+Market/data=!1sfixture123',
            'expected_name':'My Market','text':'My own visit.','stars':4,'account_email':'owner@example.com'})
        self.assertEqual(response.status_code,202)
        return response.json['review']

    def assertion(self,review,**changes):
        return {'email':review['account_email'],'name':review['expected_name'],
                'url':review['navigation_url'],'text':review['text'],'stars':review['stars'],**changes}

    def test_backend_rejects_changed_text_and_non_google_assertions(self):
        review=self.make_review()
        path=f"/api/reviews/{review['id']}/prepared"
        for changes in ({'text':'Different'},{'email':'other@example.com'},{'url':'https://evil.example/maps'},{'stars':True}):
            response=self.client.post(path,headers=self.headers,json={
                'confirmation_token':review['confirmation_token'],'assertion':self.assertion(review,**changes)})
            self.assertGreaterEqual(response.status_code,400)
        self.assertEqual(self.app.extensions['review_store'].get(review['id'])['status'],'preparing')

    def test_prepared_location_comes_from_resolved_url_and_address(self):
        review=self.make_review()
        proof=self.assertion(review, address='Main Road, Karachi',
            url=review['navigation_url']+'!3d24.8607!4d67.0011',
            latitude=99, longitude=99)
        response=self.client.post(f"/api/reviews/{review['id']}/prepared",headers=self.headers,json={
            'confirmation_token':review['confirmation_token'],'assertion':proof})
        self.assertEqual(response.status_code,200)
        saved=self.app.extensions['review_store'].get(review['id'])
        self.assertEqual(saved['business_address'],'Main Road, Karachi')
        self.assertEqual(saved['business_latitude'],24.8607)
        self.assertEqual(saved['business_longitude'],67.0011)

    def test_invalid_address_does_not_advance_preview(self):
        review=self.make_review()
        for address in (None, [], 'x'*501):
            response=self.client.post(f"/api/reviews/{review['id']}/prepared",headers=self.headers,json={
                'confirmation_token':review['confirmation_token'],
                'assertion':self.assertion(review,address=address)})
            self.assertEqual(response.status_code,400)
        self.assertEqual(self.app.extensions['review_store'].get(review['id'])['status'],'preparing')

    def test_extension_result_is_single_and_uncertainty_stays_unconfirmed(self):
        review=self.make_review();base=f"/api/reviews/{review['id']}"
        token={'confirmation_token':review['confirmation_token']}
        proof={**token,'assertion':self.assertion(review)}
        self.assertEqual(self.client.post(base+'/prepared',headers=self.headers,json=proof).status_code,200)
        self.assertEqual(self.client.post(base+'/publish',headers=self.headers,json=token).status_code,202)
        self.assertEqual(self.client.post(base+'/submitting',headers=self.headers,json=proof).status_code,200)
        self.assertEqual(self.client.post(base+'/result',headers=self.headers,json={**token,'confirmed':False}).status_code,200)
        self.assertEqual(self.client.post(base+'/result',headers=self.headers,json={**token,'confirmed':True}).status_code,409)
        self.assertEqual(self.app.extensions['review_store'].get(review['id'])['status'],'unconfirmed')

    def test_business_resolution_validates_link_and_preserves_empty_history(self):
        self.client.post('/api/browser/verified',json={'email':'owner@example.com'},headers=self.headers)
        for target in ('http://google.com/maps','https://evil.example/maps',None,'','https://www.google.com/other'):
            response=self.client.post('/api/business/resolve',json={'target':target},headers=self.headers)
            self.assertEqual(response.status_code,400)
        response=self.client.post('/api/business/resolve',json={'target':'https://maps.app.goo.gl/example'},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['navigation_url'],'https://maps.app.goo.gl/example')
        self.assertEqual(self.app.extensions['review_store'].list_reviews(),[])

    def test_reconcile_requires_matching_saved_proof_and_cannot_repost(self):
        review=self.make_review();base=f"/api/reviews/{review['id']}"
        token={'confirmation_token':review['confirmation_token']}
        proof={**token,'assertion':self.assertion(review)}
        self.client.post(base+'/prepared',headers=self.headers,json=proof)
        self.client.post(base+'/publish',headers=self.headers,json=token)
        self.client.post(base+'/submitting',headers=self.headers,json=proof)
        self.client.post(base+'/result',headers=self.headers,json={**token,'confirmed':False})
        for changes in ({'saved_review_id':''},{'text':'wrong'},{'stars':3},{'email':'other@example.com'},{'name':'Other'},{'url':'https://evil.example/maps'}):
            response=self.client.post(base+'/reconcile',headers=self.headers,json={**token,
                'assertion':self.assertion(review,**{'saved_review_id':'saved-fixture',**changes})})
            self.assertGreaterEqual(response.status_code,400)
            self.assertEqual(self.app.extensions['review_store'].get(review['id'])['status'],'unconfirmed')
        response=self.client.post(base+'/reconcile',headers=self.headers,json={**token,
            'assertion':self.assertion(review,saved_review_id='saved-fixture')})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.app.extensions['review_store'].get(review['id'])['status'],'posted')
        self.assertEqual(self.client.post(base+'/publish',headers=self.headers,json=token).status_code,409)


class RealExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start()

    @classmethod
    def tearDownClass(cls):
        cls.pw.stop()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app=create_app(Path(self.temp.name)/'data', config={"mode": "extension"})
        self.server=make_server('127.0.0.1',0,self.app,threaded=True)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        extension=str(ROOT/'chrome_extension')
        executable=Path(self.pw.chromium.executable_path)
        if not executable.exists() and os.name=='nt':
            installed=sorted((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium-*/chrome-win64/chrome.exe'))
            if installed:
                executable=installed[-1]
        self.context=self.pw.chromium.launch_persistent_context(
            str(Path(self.temp.name)/'profile'),channel='chromium',headless=True,
            executable_path=str(executable),
            args=[f'--disable-extensions-except={extension}',f'--load-extension={extension}'],
            viewport={'width':1440,'height':1000})
        self.addCleanup(self.context.close)
        self.fixture=GOOGLE.format(radios=RADIOS)
        self.widget_fixture=WIDGET.format(radios=WIDGET_RADIOS)
        self.external=[]
        def route(request):
            url=request.request.url
            if url.startswith('https://www.google.com/maps/api/js/ReviewsService.LoadWriteWidget'):
                request.fulfill(body=self.widget_fixture,content_type='text/html')
            elif url.startswith('https://www.google.com/'):
                request.fulfill(body=self.fixture,content_type='text/html')
            elif url.startswith(f'http://127.0.0.1:{self.server.server_port}/'):
                request.continue_()
            else:
                self.external.append(url)
                request.abort()
        self.context.route('**/*',route)
        # Navigate a test-owned tab first so interception is installed before any
        # Google navigation. Extension-created tabs can start loading before CDP attaches.
        self.maps_page=self.context.new_page()
        self.maps_page.goto('https://www.google.com/maps?hl=en')
        self.assertEqual(self.maps_page.evaluate('window.posts'),0)
        service=self.context.service_workers[0] if self.context.service_workers else self.context.wait_for_event('serviceworker')
        self.service=service
        service.evaluate('''() => {
            // This harness deliberately reuses its pre-intercepted Maps tab.
            // Production closes only newly created check tabs; closure is
            // asserted separately in the Node transport mocks.
            chrome.tabs.remove = async () => {};
            chrome.tabs.create = async properties => {
                const tabs=await chrome.tabs.query({url:'https://www.google.com/maps*'});
                if(tabs.length!==1) throw new Error('Missing isolated fixture tab');
                return chrome.tabs.update(tabs[0].id,properties);
            };
        }''')
        self.page=self.context.new_page()
        self.errors=[]
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.goto(f'http://127.0.0.1:{self.server.server_port}/')
        self.page.bring_to_front()
        self.page.get_by_text('Chrome extension connected',exact=True).wait_for(timeout=10000)

    def stop_server(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)

    def connect(self):
        self.page.get_by_role('button',name='Check connection',exact=True).click()
        try:
            self.page.get_by_text('Google connected',exact=True).wait_for(timeout=15000)
        except Exception:
            print('Dashboard notice:',self.page.locator('#notice').text_content())
            print('Account message:',self.page.locator('#accountMessage').text_content())
            print('Tabs:',[(page.url,page.title()) for page in self.context.pages])
            raise

    def prepare(self, target='https://www.google.com/maps/place/My+Market/data=!1sfixture123', name='My Market', open_details=True):
        self.page.locator('#target').fill(target)
        if name:
            self.page.locator('#expected_name').fill(name)
        self.page.get_by_role('radio',name='4 stars',exact=True).check()
        self.page.locator('#text').fill('My genuine visit.\nThe staff were helpful.')
        self.page.get_by_role('button',name='Start',exact=False).click()
        self.page.get_by_role('button',name='Post this review',exact=True).wait_for(timeout=15000)
        if open_details:
            self.page.locator('#previewDetails > summary').click()
        return next(page for page in self.context.pages if '/maps/place/' in page.url)

    def test_auto_business_name_and_optional_preview(self):
        self.connect()
        maps=self.prepare(name='Outdated name',open_details=False)
        self.assertEqual(self.page.locator('#expected_name').input_value(),'My Market')
        self.assertEqual(self.page.locator('#previewBusiness').inner_text(),'My Market')
        self.assertFalse(self.page.locator('#previewDetails').evaluate('(node)=>node.open'))
        self.assertTrue(self.page.get_by_role('button',name='Post this review',exact=True).is_visible())
        self.assertEqual(maps.evaluate('window.posts'),0)

    def test_link_only_fetches_details_without_creating_or_submitting_review(self):
        self.connect()
        self.page.locator('#target').fill('https://www.google.com/maps/place/My+Market/@40,50,17z/data=!1sfixture123!3d24.8607!4d67.0011')
        self.page.get_by_role('button',name='Start',exact=False).click()
        self.page.locator('#reviewStatus').get_by_text('Business found',exact=True).wait_for(timeout=10000)
        self.assertEqual(self.page.locator('#expected_name').input_value(),'My Market')
        self.page.locator('#previewDetails > summary').click()
        self.assertEqual(self.page.locator('#previewAddress').inner_text(),'Main Road, Karachi')
        self.assertEqual(self.page.locator('#previewCoordinates').inner_text(),'Place coordinates: 24.860700, 67.001100')
        self.assertEqual(self.app.extensions['review_store'].list_reviews(),[])
        self.assertEqual(self.maps_page.evaluate('window.posts'),0)
        self.assertFalse(self.page.locator('#publishButton').is_visible())

    def test_auto_fetch_ignores_results_heading_but_rejects_ambiguous_places(self):
        self.fixture=self.fixture.replace('<h1>My Market</h1>','<h1>Results</h1><h1 class="DUwDvf">My Market</h1>')
        self.connect();maps=self.prepare(name=None)
        self.assertEqual(self.page.locator('#expected_name').input_value(),'My Market')
        self.assertEqual(maps.evaluate('window.posts'),0)

    def test_extension_connection_preview_and_single_submission(self):
        self.connect()
        maps=self.prepare()
        self.assertEqual(maps.evaluate('window.posts'),0)
        self.assertEqual(maps.locator('textarea').input_value(),'My genuine visit.\nThe staff were helpful.')
        self.assertEqual(self.page.locator('#previewAddress').inner_text(),'Main Road, Karachi')
        self.assertFalse(self.page.locator('#previewCoordinates').is_visible())
        self.assertFalse(self.page.locator('#visibilityNotice').is_visible())
        self.page.get_by_role('button',name='Post this review',exact=True).click()
        self.page.locator('#reviewStatus').get_by_text('Success',exact=True).wait_for(timeout=15000)
        self.assertEqual(maps.evaluate('window.posts'),1)
        self.assertTrue(self.page.locator('#visibilityNotice').is_visible())
        self.assertEqual(self.errors,[])
        self.assertEqual(self.external,[])

    def test_changed_rating_stops_submission(self):
        self.connect();maps=self.prepare()
        maps.get_by_role('radio',name='1 star',exact=True).click()
        self.page.bring_to_front()
        self.page.get_by_role('button',name='Post this review',exact=True).click()
        self.page.locator('#reviewStatus').get_by_text('Needs attention',exact=True).wait_for(timeout=10000)
        self.assertEqual(maps.evaluate('window.posts'),0)

    def delayed_account_fixture(self):
        return self.fixture.replace('Google Account: Test (owner@example.com)', 'Google Account').replace(
            '</body>', '''<script>setTimeout(()=>document.querySelector('[aria-label="Google Account"]')
                .setAttribute('aria-label','Google Account: Test (owner@example.com)'),1200);</script></body>''')

    def test_connection_waits_for_email_not_empty_account_label(self):
        self.fixture=self.delayed_account_fixture()
        self.connect()
        self.assertEqual(self.page.locator('#connectionBadge').inner_text(),'Google connected')

    def test_prepare_waits_when_business_loads_before_account_email(self):
        self.connect()
        self.fixture=self.delayed_account_fixture()
        maps=self.prepare()
        self.assertEqual(self.page.locator('#reviewStatus').inner_text(),'Ready to post')
        self.assertEqual(maps.evaluate('window.posts'),0)

    def test_ambiguous_accounts_stop_before_opening_review_form(self):
        self.connect()
        self.fixture=self.fixture.replace('<h1>My Market</h1>',
            '<h1>My Market</h1><button aria-label="Google Account: Other (other@example.com)">Other account</button>')
        self.page.locator('#target').fill('https://www.google.com/maps/place/My+Market/data=!1sfixture123')
        self.page.locator('#expected_name').fill('My Market')
        self.page.get_by_role('radio',name='4 stars',exact=True).check()
        self.page.locator('#text').fill('My genuine visit.')
        self.page.get_by_role('button',name='Start',exact=False).click()
        self.page.locator('#notice').get_by_text('More than one Google account',exact=False).wait_for(timeout=10000)
        self.assertEqual(self.app.extensions['review_store'].list_reviews(),[])
        self.assertEqual(self.maps_page.evaluate('window.posts'),0)
        self.assertFalse(self.maps_page.locator('#writer').is_visible())

    def saved_card_fixture(self, card=SAVED_CARD):
        self.fixture=self.fixture.replace("document.querySelector('#result').textContent='Your review has been posted.'",
            "document.querySelector('#result').innerHTML=window.savedCard")
        self.fixture=self.fixture.replace('</body>','<script>window.savedCard='+json.dumps(card)+'</script></body>')

    def test_saved_own_review_card_confirms_without_success_toast(self):
        self.saved_card_fixture();self.connect();maps=self.prepare()
        self.page.get_by_role('button',name='Post this review',exact=True).click()
        self.page.locator('#reviewStatus').get_by_text('Success',exact=True).wait_for(timeout=10000)
        self.assertEqual(maps.evaluate('window.posts'),1)
        self.assertEqual(maps.locator('#result').text_content().count('Your review has been posted'),0)

    def test_read_only_reconciliation_verifies_saved_card_and_rejects_mismatches(self):
        self.connect();maps=self.prepare()
        review=self.app.extensions['review_store'].list_reviews()[0]
        # A test-owned recorded uncertain result; never submit it to Google.
        self.app.extensions['review_store'].update(review['id'],status='unconfirmed',message='Fixture uncertain submission')
        maps.locator('#result').evaluate('(node, html)=>node.innerHTML=html',SAVED_CARD)
        def check(changes):
            return self.service.evaluate('''async review=>{
                const tabs=await chrome.tabs.query({url:'https://www.google.com/maps/place/*'});
                return chrome.tabs.sendMessage(tabs[0].id,{type:'TASMEE_GOOGLE',action:'reconcile',review},{frameId:0});
            }''',{**review,**changes})
        self.assertTrue(check({})['ok'])
        for changes in ({'text':'different text'},{'stars':2},{'account_email':'other@example.com'},{'expected_name':'Other business'}):
            self.assertFalse(check(changes)['ok'])
        maps.locator('#result').evaluate('(node, html)=>node.innerHTML=html',SAVED_CARD.replace('Your review','Reviews'))
        self.assertFalse(check({})['ok'])
        self.assertEqual(maps.evaluate('window.posts'),0)

    def test_unconfirmed_review_can_be_verified_after_reload_without_reposting(self):
        self.connect();maps=self.prepare()
        review=self.app.extensions['review_store'].list_reviews()[0]
        self.app.extensions['review_store'].update(review['id'],status='unconfirmed',message='Fixture uncertain submission')
        self.fixture=self.fixture.replace('<p id="result"></p>', '<div id="result">'+SAVED_CARD+'</div>')
        self.page.reload()
        self.page.get_by_role('button',name='View My Market review, Check Google Maps',exact=True).wait_for()
        self.assertTrue(self.page.locator('#previewEmpty').is_visible())
        self.page.get_by_role('button',name='View My Market review, Check Google Maps',exact=True).click()
        self.page.get_by_role('button',name='Verify saved review',exact=True).click()
        self.page.locator('#reviewStatus').get_by_text('Success',exact=True).wait_for(timeout=15000)
        self.assertEqual(maps.evaluate('window.posts'),0)
        self.assertEqual(self.errors,[])

    def test_iframe_removal_and_saved_card_confirm_without_toast(self):
        self.use_widget()
        self.fixture=self.fixture.replace(".textContent='Your review has been posted.'",
            ".innerHTML=window.savedCard;document.querySelector('#widget-frame').remove()")
        self.fixture=self.fixture.replace('</body>','<script>window.savedCard='+json.dumps(SAVED_CARD)+'</script></body>')
        self.connect();maps=self.prepare()
        self.page.get_by_role('button',name='Post this review',exact=True).click()
        self.page.locator('#reviewStatus').get_by_text('Success',exact=True).wait_for(timeout=10000)
        self.assertEqual(maps.evaluate('window.posts'),1)
        self.assertEqual(maps.locator('#widget-frame').count(),0)

    def test_iframe_removal_without_saved_card_is_not_success(self):
        self.use_widget()
        self.fixture=self.fixture.replace(".textContent='Your review has been posted.'",
            ".textContent='';document.querySelector('#widget-frame').remove()")
        self.connect();maps=self.prepare()
        self.page.get_by_role('button',name='Post this review',exact=True).click()
        self.page.locator('#reviewStatus').get_by_text('Check Google Maps',exact=True).wait_for(timeout=25000)
        self.assertEqual(maps.evaluate('window.posts'),1)

    def test_location_coordinates_from_resolved_place_not_camera(self):
        self.connect()
        maps=self.prepare('https://www.google.com/maps/place/My+Market/@40,50,17z/data=!1sfixture123!3d24.8607!4d67.0011')
        self.assertEqual(self.page.locator('#previewAddress').inner_text(),'Main Road, Karachi')
        self.assertEqual(self.page.locator('#previewCoordinates').inner_text(),'Place coordinates: 24.860700, 67.001100')
        self.assertEqual(maps.evaluate('window.posts'),0)

    def test_ambiguous_address_shows_unavailable(self):
        self.fixture=self.fixture.replace('<h1>My Market</h1>',
            '<h1>My Market</h1><button data-item-id="address" aria-label="Address: Other Road">Other Road</button>')
        self.connect();maps=self.prepare()
        self.assertIn('Address available nahi hai',self.page.locator('#previewAddress').inner_text())
        self.assertFalse(self.page.locator('#previewCoordinates').is_visible())
        self.assertEqual(maps.evaluate('window.posts'),0)

    def use_widget(self, url=WIDGET_URL):
        self.fixture=self.fixture.replace("document.querySelector('#writer').hidden=false", "openWriter()")
        self.fixture=self.fixture.replace('</body>', '''<script>
            function openWriter(){const frame=document.createElement('iframe');frame.id='widget-frame';
                frame.src=URL;frame.style='width:800px;height:600px';document.body.append(frame)}
            window.addEventListener('message',event=>{if(event.source===document.querySelector('#widget-frame')?.contentWindow
                && event.data?.type==='FIXTURE_POSTED'){window.posts++;document.querySelector('#result')
                .textContent='Your review has been posted.'}});
            </script></body>'''.replace('frame.src=URL', 'frame.src='+json.dumps(url)))

    def test_iframe_overall_stars_text_preview_and_dashboard_only_submission(self):
        self.use_widget();self.connect();maps=self.prepare()
        frame=maps.frame_locator('#widget-frame')
        overall=frame.get_by_role('radiogroup',name='Rating stars',exact=True)
        self.assertEqual(overall.get_by_role('radio',name='Four stars',exact=True).get_attribute('aria-checked'),'true')
        self.assertEqual(frame.get_by_role('radiogroup',name='Food rating stars',exact=True)
            .locator('[aria-checked="true"]').count(),0)
        self.assertEqual(frame.get_by_role('textbox',name='Enter review',exact=True).input_value(),
            'My genuine visit.\nThe staff were helpful.')
        self.assertEqual(maps.evaluate('window.posts'),0)
        self.assertEqual(self.page.locator('#previewAddress').inner_text(),'Main Road, Karachi')
        self.page.get_by_role('button',name='Post this review',exact=True).click()
        self.page.locator('#reviewStatus').get_by_text('Success',exact=True).wait_for(timeout=10000)
        self.assertEqual(maps.evaluate('window.posts'),1)
        self.assertEqual(self.errors,[])
        self.assertEqual(self.external,[])

    def test_changed_iframe_rating_stops_dashboard_submission(self):
        self.use_widget();self.connect();maps=self.prepare()
        maps.frame_locator('#widget-frame').get_by_role('radiogroup',name='Rating stars',exact=True)\
            .get_by_role('radio',name='One star',exact=True).click()
        self.page.bring_to_front()
        self.page.get_by_role('button',name='Post this review',exact=True).click()
        self.page.locator('#reviewStatus').get_by_text('Needs attention',exact=True).wait_for(timeout=10000)
        self.assertEqual(maps.evaluate('window.posts'),0)

    def test_iframe_submit_without_dashboard_phase_is_rejected(self):
        self.use_widget();self.connect();maps=self.prepare()
        review=self.app.extensions['review_store'].list_reviews()[0]
        result=self.service.evaluate('''async data=>{
            const tabs=await chrome.tabs.query({url:'https://www.google.com/maps/place/*'});
            try {await widgetRequest({action:'submit',review:data.review,url:data.url},
                {id:chrome.runtime.id,frameId:0,tab:tabs[0],url:tabs[0].url});return {ok:true}}
            catch(error){return {ok:false,message:error.message}}
        }''',{'review':review,'url':WIDGET_URL})
        self.assertFalse(result['ok'])
        self.assertIn('not authorized',result['message'])
        self.assertEqual(maps.evaluate('window.posts'),0)

    def test_different_iframe_account_is_rejected_before_filling(self):
        self.use_widget(WIDGET_URL.replace('authuser=0','authuser=1'));self.connect()
        self.page.locator('#target').fill('https://www.google.com/maps/place/My+Market/data=!1sfixture123')
        self.page.locator('#expected_name').fill('My Market')
        self.page.get_by_role('radio',name='4 stars',exact=True).check()
        self.page.locator('#text').fill('My genuine visit.')
        self.page.get_by_role('button',name='Start',exact=False).click()
        self.page.locator('#reviewStatus').get_by_text('Needs attention',exact=True).wait_for(timeout=10000)
        self.assertIn('different Google account',self.page.locator('#reviewMessage').inner_text())
        self.assertEqual(self.maps_page.frame_locator('#widget-frame').get_by_role('textbox',name='Enter review').input_value(),'')
        self.assertEqual(self.maps_page.evaluate('window.posts'),0)

    def test_direct_script_submission_has_no_user_gesture(self):
        self.connect();maps=self.prepare()
        review=self.app.extensions['review_store'].list_reviews()[0]
        result=self.page.evaluate('''review => new Promise(resolve=>{
          const id=crypto.randomUUID();
          const receive=event=>{if(event.data?.id===id && event.data.type==='TASMEE_RESPONSE'){window.removeEventListener('message',receive);resolve(event.data.response)}};
          window.addEventListener('message',receive);
          window.postMessage({type:'TASMEE_REQUEST',id,action:'submit',data:{review}},location.origin);
        })''',review)
        self.assertFalse(result['ok'])
        self.assertIn('authorize',result['message'])
        self.assertEqual(maps.evaluate('window.posts'),0)


if __name__=='__main__':
    unittest.main()
