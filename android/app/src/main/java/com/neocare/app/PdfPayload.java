package com.neocare.app;

import java.util.Base64;

/** Bounded, validated PDF data; the system picker determines its destination. */
public final class PdfPayload {
    public static final int MAX_BYTES = 8 * 1024 * 1024;
    public static final int MAX_BASE64_CHARS = ((MAX_BYTES + 2) / 3) * 4;
    public final byte[] bytes;
    public final String filename;

    private PdfPayload(byte[] bytes, String filename) {
        this.bytes = bytes;
        this.filename = filename;
    }

    public static PdfPayload decode(String base64, String mimeType, String suggestedName) {
        if (!"application/pdf".equals(mimeType) || base64 == null
                || base64.length() > MAX_BASE64_CHARS || base64.length() < 8) {
            throw new IllegalArgumentException("Invalid PDF payload");
        }
        byte[] data;
        try {
            data = Base64.getDecoder().decode(base64);
        } catch (IllegalArgumentException invalidBase64) {
            throw new IllegalArgumentException("Invalid PDF payload");
        }
        if (data.length > MAX_BYTES || data.length < 5 || data[0] != '%' || data[1] != 'P'
                || data[2] != 'D' || data[3] != 'F' || data[4] != '-') {
            throw new IllegalArgumentException("Invalid PDF payload");
        }
        return new PdfPayload(data, safeFilename(suggestedName));
    }

    public static String safeFilename(String suggestedName) {
        String name = suggestedName == null ? "NEOCARE_Report" : suggestedName;
        if (name.toLowerCase(java.util.Locale.ROOT).endsWith(".pdf")) name = name.substring(0, name.length() - 4);
        name = name.replaceAll("[^A-Za-z0-9_-]", "_");
        if (name.length() > 92) name = name.substring(0, 92);
        if (name.isEmpty() || name.replace("_", "").isEmpty()) name = "NEOCARE_Report";
        return name + ".pdf";
    }
}
