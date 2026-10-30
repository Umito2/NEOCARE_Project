package com.neocare.app;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class HostPolicyTest {
    @Test public void trustedOriginAllowsItsHttpsPagesAndDefaultPort() {
        for (String value : new String[] {
                "https://umito.pythonanywhere.com/",
                "https://umito.pythonanywhere.com",
                "https://umito.pythonanywhere.com:443/api/v1/children?period=24h",
                "https://umito.pythonanywhere.com/#clinic"}) {
            assertTrue(value, HostPolicy.isTrusted(value));
        }
    }

    @Test public void lookalikesCredentialsPortsAndLocalSchemesAreNeverTrusted() {
        for (String value : new String[] {
                null, "", "/", "not a URL", "//umito.pythonanywhere.com/",
                "http://umito.pythonanywhere.com/", "https://umito.pythonanywhere.com:444/",
                "https://umito.pythonanywhere.com.evil.example/",
                "https://evil.example/umito.pythonanywhere.com/",
                "https://evil.example@umito.pythonanywhere.com/",
                "https://umito.pythonanywhere.com@evil.example/",
                "https://umito.pythonanywhere.com%2eevil.example/",
                "https://umito.pythonanywhere.com\\@evil.example/",
                "https://umito.pythonanywhere.com./",
                "file:///sdcard/report.pdf", "content://example/report",
                "javascript:alert(1)", "data:text/html,hello", "intent://example/#Intent;end"}) {
            assertFalse(String.valueOf(value), HostPolicy.isTrusted(value));
        }
    }

    @Test public void externalBrowserPolicyAcceptsHttpsWithoutUserInformation() {
        assertTrue(HostPolicy.isExternalHttps("https://example.org/help"));
        for (String value : new String[] {
                null, "", "http://example.org/", "https://user:password@example.org/",
                "file:///sdcard/report.pdf", "javascript:alert(1)",
                "intent://example/#Intent;scheme=https;end", "https:///missing-host"}) {
            assertFalse(String.valueOf(value), HostPolicy.isExternalHttps(value));
        }
    }
}
