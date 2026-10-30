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
import android.net.Uri;
import android.security.NetworkSecurityPolicy;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebViewClient;

import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;

import java.util.Collections;
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

    @Test public void mainFrameNetworkFailureShowsRetryWithoutReplacingItForAnAssetFailure() {
        scenario.onActivity(activity -> {
            activity.errorPanel.setVisibility(View.GONE);
            WebViewClient client = activity.webView.getWebViewClient();
            client.onReceivedError(activity.webView, request(false), offlineError());
            assertEquals(View.GONE, activity.errorPanel.getVisibility());
            client.onReceivedError(activity.webView, request(true), offlineError());
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
        syntheticPage(HostPolicy.HOME);
        javascript("history.pushState({}, '', '/__neocare_synthetic_second'); true");
        scenario.onActivity(activity -> {
            assertTrue(activity.webView.canGoBack());
            activity.navigateBack();
            assertFalse(activity.isFinishing());
        });
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (System.nanoTime() < deadline) {
            if ("\"/\"".equals(javascript("location.pathname"))) return;
            Thread.sleep(50);
        }
        throw new AssertionError("Back did not restore the previous page");
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

    private static WebResourceError offlineError() {
        return new WebResourceError() {
            @Override public int getErrorCode() { return WebViewClient.ERROR_HOST_LOOKUP; }
            @Override public CharSequence getDescription() { return "Synthetic connection failure"; }
        };
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
