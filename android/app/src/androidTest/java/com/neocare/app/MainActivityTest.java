package com.neocare.app;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.net.Uri;
import android.security.NetworkSecurityPolicy;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;

import java.util.Collections;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Synthetic pages and error callbacks only; never submits credentials or records. */
@RunWith(AndroidJUnit4.class)
public final class MainActivityTest {
    private ActivityScenario<MainActivity> scenario;
    private final Instrumentation instrumentation = InstrumentationRegistry.getInstrumentation();

    @Before public void launchActivity() {
        Intent intent = new Intent(instrumentation.getTargetContext(), MainActivity.class);
        scenario = ActivityScenario.launch(intent);
        scenario.onActivity(activity -> activity.webView.stopLoading());
    }

    @After public void closeActivity() {
        if (scenario != null) scenario.close();
    }

    @Test public void launchUsesRestrictedFirstPartyWebViewSettings() {
        scenario.onActivity(activity -> {
            WebSettings settings = activity.webView.getSettings();
            assertTrue(settings.getJavaScriptEnabled());
            assertTrue(settings.getDomStorageEnabled());
            assertFalse(settings.getAllowFileAccess());
            assertFalse(settings.getAllowContentAccess());
            assertFalse(settings.getJavaScriptCanOpenWindowsAutomatically());
            assertEquals(WebSettings.MIXED_CONTENT_NEVER_ALLOW, settings.getMixedContentMode());
            assertFalse(CookieManager.getInstance().acceptThirdPartyCookies(activity.webView));
            assertTrue(CookieManager.getInstance().acceptCookie());
            assertFalse(NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted("umito.pythonanywhere.com"));
        });
    }

    @Test public void applicationHasNoStorageSensorPermissionsOrBackup() throws Exception {
        PackageManager manager = instrumentation.getTargetContext().getPackageManager();
        PackageInfo info = manager.getPackageInfo(instrumentation.getTargetContext().getPackageName(),
                PackageManager.GET_PERMISSIONS);
        Set<String> systemPermissions = new HashSet<>();
        if (info.requestedPermissions != null) {
            for (String permission : info.requestedPermissions) {
                if (permission.startsWith("android.permission.")) systemPermissions.add(permission);
            }
        }
        assertEquals(Collections.singleton("android.permission.INTERNET"), systemPermissions);
        assertNotNull(info.applicationInfo);
        assertEquals(0, info.applicationInfo.flags & ApplicationInfo.FLAG_ALLOW_BACKUP);
    }

    @Test public void mainFrameHttpFailureShowsRetryWithoutReplacingItForAnAssetFailure() {
        scenario.onActivity(activity -> {
            activity.errorPanel.setVisibility(View.GONE);
            WebViewClient client = activity.webView.getWebViewClient();
            client.onReceivedHttpError(activity.webView, request(false), unavailableResponse());
            assertEquals(View.GONE, activity.errorPanel.getVisibility());
            client.onReceivedHttpError(activity.webView, request(true), unavailableResponse());
            assertEquals(View.VISIBLE, activity.errorPanel.getVisibility());
            assertNotNull(activity.findViewById(R.id.retry_button));
        });
    }

    @Test public void trustedBlobDownloadOpensPdfPickerEvenAfterImmediateUrlRevocation() throws Exception {
        syntheticPage(HostPolicy.HOME);
        assertEquals("\"object\"", javascript("typeof window.NEOCAREAndroid"));
        Instrumentation.ActivityMonitor monitor = pdfPickerMonitor();
        try {
            javascript("(() => { const blob = new Blob(['%PDF-1.7\\n% synthetic fixture\\n%%EOF\\n'],"
                    + "{type:'application/pdf'}); const a = document.createElement('a');"
                    + "a.href=URL.createObjectURL(blob); a.download='Synthetic.pdf';"
                    + "a.click(); URL.revokeObjectURL(a.href); return true; })()");
            awaitPicker(monitor);
            assertEquals(1, monitor.getHits());
        } finally {
            instrumentation.removeMonitor(monitor);
        }
    }

    @Test public void nativeExportRefusesUntrustedOriginAndChildFrameMessages() throws Exception {
        syntheticPage(HostPolicy.HOME);
        Instrumentation.ActivityMonitor monitor = pdfPickerMonitor();
        try {
            String message = "{\"op\":\"savePdf\",\"data\":\"JVBERi0xLjcKJSBzeW50aGV0aWMK\","
                    + "\"mimeType\":\"application/pdf\",\"filename\":\"Synthetic.pdf\"}";
            scenario.onActivity(activity -> {
                activity.handleWebMessage(message, Uri.parse("https://evil.example"), true);
                activity.handleWebMessage(message, Uri.parse(HostPolicy.ORIGIN), false);
            });
            instrumentation.waitForIdleSync();
            assertEquals(0, monitor.getHits());
        } finally {
            instrumentation.removeMonitor(monitor);
        }
    }

    @Test public void bridgeObjectIsAbsentOnAnUntrustedOrigin() throws Exception {
        // Isolate the bridge's own origin rule from the production navigation guard.
        // The only page loaded here is the local synthetic fixture below.
        scenario.onActivity(activity -> activity.webView.setWebViewClient(new WebViewClient()));
        syntheticPage("https://untrusted.example/");
        assertEquals("\"undefined\"", javascript("typeof window.NEOCAREAndroid"));
    }

    @Test public void backReturnsThroughWebHistoryWithoutClosingTheActivity() throws Exception {
        String first = HostPolicy.ORIGIN + "/__neocare_android_test_first";
        String second = HostPolicy.ORIGIN + "/__neocare_android_test_second";
        AtomicReference<String> finished = new AtomicReference<>("");
        scenario.onActivity(activity -> {
            activity.webView.stopLoading();
            WebViewClient productionClient = activity.webView.getWebViewClient();
            activity.webView.setWebViewClient(new WebViewClient() {
                @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                    String url = request.getUrl().toString();
                    if (!first.equals(url) && !second.equals(url)) return unavailableResponse();
                    byte[] html = ("<!doctype html><meta charset='utf-8'><title>NEOCARE synthetic history</title>"
                            + "<p id='fixture'>" + (first.equals(url) ? "first" : "second") + "</p>")
                            .getBytes(StandardCharsets.UTF_8);
                    return new WebResourceResponse("text/html", "UTF-8", 200, "OK",
                            Collections.singletonMap("Cache-Control", "no-store"),
                            new java.io.ByteArrayInputStream(html));
                }

                @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                    return productionClient.shouldOverrideUrlLoading(view, request);
                }

                @Override public void onPageStarted(WebView view, String url, Bitmap icon) {
                    productionClient.onPageStarted(view, url, icon);
                }

                @Override public void onPageFinished(WebView view, String url) {
                    productionClient.onPageFinished(view, url);
                    finished.set(url);
                }
            });
            activity.webView.loadUrl(first);
        });
        awaitDocument(finished, first, "first");
        scenario.onActivity(activity -> activity.webView.loadUrl(second));
        awaitDocument(finished, second, "second");

        // Document navigations create real native history entries. A pushState
        // in loadDataWithBaseURL can be ignored by Chromium's history policy.
        AtomicReference<Boolean> canGoBack = new AtomicReference<>(false);
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
        while (!canGoBack.get() && System.nanoTime() < deadline) {
            scenario.onActivity(activity -> canGoBack.set(activity.webView.canGoBack()));
            if (!canGoBack.get()) Thread.sleep(50);
        }
        assertTrue("The two document navigations must create native history", canGoBack.get());
        finished.set("");
        scenario.onActivity(activity -> {
            assertTrue(activity.webView.canGoBack());
            activity.navigateBack();
            assertFalse(activity.isFinishing());
        });
        awaitDocument(finished, first, "first");
        scenario.onActivity(activity -> assertFalse(activity.isFinishing()));
    }

    private void awaitDocument(AtomicReference<String> finished, String url, String text) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
        while (System.nanoTime() < deadline) {
            if (url.equals(finished.get()) && "true".equals(javascript(
                    "document.getElementById('fixture')?.textContent === '" + text + "'"))) return;
            Thread.sleep(50);
        }
        throw new AssertionError("The expected synthetic history document did not finish loading");
    }

    private Instrumentation.ActivityMonitor pdfPickerMonitor() throws Exception {
        IntentFilter filter = new IntentFilter(Intent.ACTION_CREATE_DOCUMENT);
        filter.addCategory(Intent.CATEGORY_OPENABLE);
        filter.addDataType("application/pdf");
        Instrumentation.ActivityMonitor monitor = new Instrumentation.ActivityMonitor(filter,
                new Instrumentation.ActivityResult(Activity.RESULT_CANCELED, null), true);
        instrumentation.addMonitor(monitor);
        return monitor;
    }

    private static void awaitPicker(Instrumentation.ActivityMonitor monitor) throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
        while (System.nanoTime() < deadline) {
            if (monitor.getHits() > 0) return;
            Thread.sleep(50);
        }
        throw new AssertionError("The PDF export did not open the system picker");
    }

    private static WebResourceRequest request(boolean mainFrame) {
        return new WebResourceRequest() {
            @Override public Uri getUrl() { return Uri.parse(HostPolicy.HOME); }
            @Override public boolean isForMainFrame() { return mainFrame; }
            @Override public boolean isRedirect() { return false; }
            @Override public boolean hasGesture() { return false; }
            @Override public String getMethod() { return "GET"; }
            @Override public Map<String, String> getRequestHeaders() { return Collections.emptyMap(); }
        };
    }

    private static WebResourceResponse unavailableResponse() {
        return new WebResourceResponse("text/plain", "UTF-8", 503, "Service Unavailable",
                Collections.emptyMap(), new java.io.ByteArrayInputStream(new byte[0]));
    }

    private String javascript(String expression) throws InterruptedException {
        CountDownLatch completed = new CountDownLatch(1);
        AtomicReference<String> value = new AtomicReference<>();
        scenario.onActivity(activity -> activity.webView.evaluateJavascript(expression, result -> {
            value.set(result);
            completed.countDown();
        }));
        assertTrue("JavaScript callback timed out", completed.await(10, TimeUnit.SECONDS));
        return value.get();
    }

    private void syntheticPage(String origin) throws Exception {
        scenario.onActivity(activity -> {
            activity.webView.stopLoading();
            activity.webView.loadDataWithBaseURL(origin,
                    "<!doctype html><meta charset='utf-8'><title>NEOCARE synthetic test</title>"
                            + "<p id='fixture'>Synthetic content only</p>",
                    "text/html", "UTF-8", origin);
        });
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
        while (System.nanoTime() < deadline) {
            if ("true".equals(javascript("document.getElementById('fixture') !== null"))) return;
            Thread.sleep(50);
        }
        throw new AssertionError("Synthetic page did not finish loading");
    }
}
