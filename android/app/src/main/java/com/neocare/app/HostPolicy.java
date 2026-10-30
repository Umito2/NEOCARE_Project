package com.neocare.app;

import java.net.URI;
import java.net.URISyntaxException;

/** One fixed first-party origin; no URL supplied by another app changes it. */
public final class HostPolicy {
    public static final String ORIGIN = "https://umito.pythonanywhere.com";
    public static final String HOME = ORIGIN + "/";

    private HostPolicy() { }

    public static boolean isTrusted(String value) {
        URI uri = parseHttps(value);
        return uri != null && "umito.pythonanywhere.com".equalsIgnoreCase(uri.getHost());
    }

    public static boolean isExternalHttps(String value) {
        return parseHttps(value) != null && !isTrusted(value);
    }

    private static URI parseHttps(String value) {
        if (value == null || value.indexOf('\\') >= 0 || value.length() > 8192) return null;
        try {
            URI uri = new URI(value);
            if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null
                    || uri.getUserInfo() != null || (uri.getPort() != -1 && uri.getPort() != 443)) return null;
            return uri;
        } catch (URISyntaxException exception) {
            return null;
        }
    }
}
