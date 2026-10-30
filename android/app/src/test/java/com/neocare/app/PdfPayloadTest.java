package com.neocare.app;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Base64;
import org.junit.Test;

public final class PdfPayloadTest {
    private static final byte[] PDF = "%PDF-1.7\n% synthetic test document\n%%EOF\n"
            .getBytes(StandardCharsets.US_ASCII);

    private static String encoded(byte[] bytes) {
        return Base64.getEncoder().encodeToString(bytes);
    }

    @Test public void realPdfBytesRoundTripWithoutChangingTheirContents() {
        PdfPayload result = PdfPayload.decode(encoded(PDF), "application/pdf", "NEOCARE-report.pdf");
        assertArrayEquals(PDF, result.bytes);
        assertTrue(result.filename.endsWith(".pdf"));
    }

    @Test public void mimeAndHeaderMustBothDescribeAPdf() {
        assertThrows(IllegalArgumentException.class,
                () -> PdfPayload.decode(encoded(PDF), "text/html", "report.pdf"));
        assertThrows(IllegalArgumentException.class,
                () -> PdfPayload.decode(encoded("<html>not a PDF</html>".getBytes(StandardCharsets.UTF_8)),
                        "application/pdf", "report.pdf"));
        assertThrows(IllegalArgumentException.class,
                () -> PdfPayload.decode(encoded(new byte[0]), "application/pdf", "report.pdf"));
        assertThrows(IllegalArgumentException.class,
                () -> PdfPayload.decode("not valid base64!?", "application/pdf", "report.pdf"));
    }

    @Test public void decodedLimitStopsOversizedExportsBeforeSaving() {
        byte[] oversized = new byte[PdfPayload.MAX_BYTES + 1];
        Arrays.fill(oversized, (byte) ' ');
        System.arraycopy(PDF, 0, oversized, 0, PDF.length);
        assertThrows(IllegalArgumentException.class,
                () -> PdfPayload.decode(encoded(oversized), "application/pdf", "report.pdf"));
    }

    @Test public void filenamesCannotContainPathsControlsOrUnboundedNames() {
        for (String name : new String[] {
                "../../outside.pdf", "C:\\private\\outside.pdf", "report\r\n\u0000.pdf",
                "", ".", "..", "x".repeat(300) + ".pdf", "report.html"}) {
            String filename = PdfPayload.decode(encoded(PDF), "application/pdf", name).filename;
            assertTrue(filename, filename.endsWith(".pdf"));
            assertTrue(filename, filename.length() <= 96);
            assertTrue(filename, filename.length() > 4);
            assertFalse(filename, filename.contains("/") || filename.contains("\\"));
            assertTrue(filename, filename.chars().noneMatch(Character::isISOControl));
        }
    }
}
