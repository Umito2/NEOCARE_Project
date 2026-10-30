package com.neocare.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.res.Configuration;
import android.graphics.Insets;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.print.PrintManager;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.webkit.CookieManager;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import android.window.OnBackInvokedCallback;
import android.window.OnBackInvokedDispatcher;

import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Collections;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Android shell for the existing first-party NEOCARE website. */
public class MainActivity extends Activity {
    private static final int CREATE_PDF = 7001;
    private static final String BRIDGE = "NEOCAREAndroid";
    private final ExecutorService fileWriter = Executors.newSingleThreadExecutor();
    WebView webView;
    FrameLayout errorPanel;
    ProgressBar progressBar;
    private FrameLayout webContainer;
    private TextView errorMessage;
    private PdfPayload pendingPdf;
    private boolean pageFailed;
    private boolean bridgeSupported;
    private boolean unsupportedNoticeShown;
    private String reportScript;
    private OnBackInvokedCallback backCallback;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        reportScript = readReportScript();
        buildLayout();
        createWebView();
        if (Build.VERSION.SDK_INT >= 33) {
            backCallback = this::navigateBack;
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    OnBackInvokedDispatcher.PRIORITY_DEFAULT, backCallback);
        }
        loadHome();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @SuppressWarnings("deprecation")
    private void buildLayout() {
        if (Build.VERSION.SDK_INT >= 30) getWindow().setDecorFitsSystemWindows(false);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(getColor(R.color.app_background));
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                int bottom = Math.max(bars.bottom, insets.getInsets(WindowInsets.Type.ime()).bottom);
                view.setPadding(bars.left, bars.top, bars.right, bottom);
            } else {
                view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                        insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            }
            return insets;
        });
        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setId(R.id.progress_bar);
        progressBar.setMax(100);
        root.addView(progressBar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(3)));
        webContainer = new FrameLayout(this);
        root.addView(webContainer, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));

        errorPanel = new FrameLayout(this);
        errorPanel.setId(R.id.error_panel);
        errorPanel.setBackgroundColor(getColor(R.color.app_background));
        LinearLayout messageBox = new LinearLayout(this);
        messageBox.setOrientation(LinearLayout.VERTICAL);
        messageBox.setGravity(Gravity.CENTER);
        messageBox.setPadding(dp(24), dp(24), dp(24), dp(24));
        TextView title = new TextView(this);
        title.setText(R.string.connection_title);
        title.setTextSize(22);
        title.setTextColor(getColor(R.color.app_text));
        title.setGravity(Gravity.CENTER);
        messageBox.addView(title);
        errorMessage = new TextView(this);
        errorMessage.setText(R.string.connection_message);
        errorMessage.setTextSize(16);
        errorMessage.setGravity(Gravity.CENTER);
        errorMessage.setTextColor(getColor(R.color.app_text));
        errorMessage.setPadding(0, dp(16), 0, dp(16));
        messageBox.addView(errorMessage);
        Button retry = new Button(this);
        retry.setId(R.id.retry_button);
        retry.setText(R.string.retry);
        retry.setOnClickListener(view -> loadHome());
        messageBox.addView(retry);
        Button browser = new Button(this);
        browser.setText(R.string.open_website);
        browser.setOnClickListener(view -> openExternal(HostPolicy.HOME));
        messageBox.addView(browser);
        errorPanel.addView(messageBox, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER));
        errorPanel.setVisibility(View.GONE);
        webContainer.addView(errorPanel, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);
        root.requestApplyInsets();
    }

    @SuppressLint("SetJavaScriptEnabled")
    @SuppressWarnings("deprecation")
    private void createWebView() {
        webView = new WebView(this);
        webView.setId(R.id.webview);
        webView.setSaveEnabled(false);
        webView.setBackgroundColor(getColor(R.color.app_background));
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setSafeBrowsingEnabled(true);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false);
        webView.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView view, int progress) {
                progressBar.setProgress(progress);
                progressBar.setVisibility(progress >= 100 || pageFailed ? View.GONE : View.VISIBLE);
            }
        });
        webView.setWebViewClient(new SiteClient());
        webView.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) ->
                toast(bridgeSupported ? R.string.download_failed : R.string.update_webview));

        bridgeSupported = WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)
                && reportScript != null;
        if (bridgeSupported && WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            WebViewCompat.addWebMessageListener(webView, BRIDGE, Collections.singleton(HostPolicy.ORIGIN),
                    (view, message, sourceOrigin, isMainFrame, replyProxy) -> {
                        if (message.getType() == androidx.webkit.WebMessageCompat.TYPE_STRING) {
                            handleWebMessage(message.getData(), sourceOrigin, isMainFrame);
                        }
                    });
            if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
                WebViewCompat.addDocumentStartJavaScript(webView, reportScript, Collections.singleton(HostPolicy.ORIGIN));
            }
        }
        webContainer.addView(webView, 0, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private String readReportScript() {
        try (InputStream stream = getAssets().open("native-reports.js")) {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int count;
            while ((count = stream.read(buffer)) != -1) output.write(buffer, 0, count);
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        } catch (IOException error) {
            return null;
        }
    }

    private void loadHome() {
        pageFailed = false;
        errorPanel.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        progressBar.setProgress(0);
        progressBar.setVisibility(View.VISIBLE);
        webView.loadUrl(HostPolicy.HOME);
    }

    private void showPageError(int message) {
        pageFailed = true;
        progressBar.setVisibility(View.GONE);
        webView.setVisibility(View.GONE);
        errorMessage.setText(message);
        errorPanel.setVisibility(View.VISIBLE);
    }

    private class SiteClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            String target = request.getUrl().toString();
            if (HostPolicy.isTrusted(target)) return false;
            if (request.isForMainFrame() && request.hasGesture() && HostPolicy.isExternalHttps(target)) {
                openExternal(target);
            }
            return true;
        }

        @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
            if (!HostPolicy.isTrusted(url)) {
                view.stopLoading();
                showPageError(R.string.secure_connection_message);
                return;
            }
            pageFailed = false;
            progressBar.setVisibility(View.VISIBLE);
        }

        @Override public void onPageFinished(WebView view, String url) {
            if (pageFailed || !HostPolicy.isTrusted(url)) return;
            errorPanel.setVisibility(View.GONE);
            view.setVisibility(View.VISIBLE);
            progressBar.setVisibility(View.GONE);
            if (bridgeSupported) view.evaluateJavascript(reportScript, null);
            else if (!unsupportedNoticeShown) {
                unsupportedNoticeShown = true;
                new AlertDialog.Builder(MainActivity.this)
                        .setMessage(R.string.update_webview)
                        .setPositiveButton(R.string.open_website, (dialog, which) -> openExternal(HostPolicy.HOME))
                        .setNegativeButton(android.R.string.ok, null).show();
            }
            CookieManager.getInstance().flush();
        }

        @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) showPageError(R.string.connection_message);
        }

        @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
            if (request.isForMainFrame() && response.getStatusCode() >= 400) showPageError(R.string.connection_message);
        }

        @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
            handler.cancel();
            showPageError(R.string.secure_connection_message);
        }

        @Override public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
            clearPendingPdf();
            webContainer.removeView(view);
            view.destroy();
            createWebView();
            showPageError(R.string.connection_message);
            return true;
        }
    }

    void handleWebMessage(String json, Uri sourceOrigin, boolean isMainFrame) {
        if (!isMainFrame || sourceOrigin == null || !HostPolicy.isTrusted(sourceOrigin.toString())
                || webView == null || !HostPolicy.isTrusted(webView.getUrl()) || json == null
                || json.length() > PdfPayload.MAX_BASE64_CHARS + 1024) return;
        try {
            JSONObject message = new JSONObject(json);
            switch (message.getString("op")) {
                case "savePdf":
                    if (pendingPdf != null) {
                        toast(R.string.download_busy);
                        return;
                    }
                    PdfPayload pdf = PdfPayload.decode(message.getString("data"),
                            message.getString("mimeType"), message.optString("filename", "NEOCARE_Report.pdf"));
                    pendingPdf = pdf;
                    Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                    intent.addCategory(Intent.CATEGORY_OPENABLE);
                    intent.setType("application/pdf");
                    intent.putExtra(Intent.EXTRA_TITLE, pdf.filename);
                    try {
                        startActivityForResult(intent, CREATE_PDF);
                    } catch (ActivityNotFoundException noPicker) {
                        clearPendingPdf();
                        toast(R.string.no_document_app);
                    }
                    break;
                case "print":
                    PrintManager printer = (PrintManager) getSystemService(PRINT_SERVICE);
                    if (printer == null) toast(R.string.print_failed);
                    else {
                        try {
                            printer.print("NEOCARE_Report", webView.createPrintDocumentAdapter("NEOCARE_Report"), null);
                        } catch (IllegalStateException unavailable) {
                            toast(R.string.print_failed);
                        }
                    }
                    break;
                case "downloadError":
                    toast(R.string.download_failed);
                    break;
                default:
                    break;
            }
        } catch (JSONException | IllegalArgumentException invalid) {
            toast(R.string.download_failed);
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent result) {
        super.onActivityResult(requestCode, resultCode, result);
        if (requestCode != CREATE_PDF) return;
        PdfPayload pdf = pendingPdf;
        pendingPdf = null;
        Uri destination = result == null ? null : result.getData();
        if (pdf == null) return;
        if (resultCode != RESULT_OK || destination == null || !"content".equals(destination.getScheme())) {
            Arrays.fill(pdf.bytes, (byte) 0);
            return;
        }
        fileWriter.execute(() -> {
            boolean saved = false;
            try (OutputStream output = getContentResolver().openOutputStream(destination, "w")) {
                if (output != null) {
                    output.write(pdf.bytes);
                    output.flush();
                    saved = true;
                }
            } catch (IOException | SecurityException ignored) {
                // Report only a generic failure; report contents and destination stay private.
            } finally {
                Arrays.fill(pdf.bytes, (byte) 0);
            }
            final boolean success = saved;
            runOnUiThread(() -> {
                if (!isFinishing() && !isDestroyed()) toast(success ? R.string.download_saved : R.string.download_failed);
            });
        });
    }

    private void clearPendingPdf() {
        if (pendingPdf != null) {
            Arrays.fill(pendingPdf.bytes, (byte) 0);
            pendingPdf = null;
        }
    }

    private void openExternal(String url) {
        if (!HostPolicy.isTrusted(url) && !HostPolicy.isExternalHttps(url)) return;
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE));
        } catch (ActivityNotFoundException unavailable) {
            toast(R.string.no_browser);
        }
    }

    private void toast(int resource) {
        Toast.makeText(this, resource, Toast.LENGTH_LONG).show();
    }

    void navigateBack() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else finish();
    }

    // Android 13+ gestures use the registered OnBackInvokedCallback above.
    // This override serves only the legacy Back dispatch on Android 8–12.
    @Override @SuppressWarnings("deprecation")
    @SuppressLint("GestureBackNavigation")
    public void onBackPressed() {
        navigateBack();
    }

    @Override protected void onPause() {
        CookieManager.getInstance().flush();
        if (webView != null) webView.onPause();
        super.onPause();
    }

    @Override protected void onResume() {
        super.onResume();
        if (webView != null) webView.onResume();
    }

    @Override public void onConfigurationChanged(Configuration configuration) {
        super.onConfigurationChanged(configuration);
        if (webView != null) webView.requestApplyInsets();
    }

    @Override protected void onDestroy() {
        if (Build.VERSION.SDK_INT >= 33 && backCallback != null) {
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback(backCallback);
        }
        clearPendingPdf();
        fileWriter.shutdown();
        if (webView != null) {
            webContainer.removeView(webView);
            webView.stopLoading();
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }
}
