package com.neocare.app;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.util.Base64;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public final class PendingPdfStoreTest {
    @Rule public final TemporaryFolder temporary = new TemporaryFolder();
    private static final byte[] PDF = "%PDF-1.7\n% synthetic report\n%%EOF\n"
            .getBytes(StandardCharsets.US_ASCII);

    private PdfPayload pdf() {
        return PdfPayload.decode(Base64.getEncoder().encodeToString(PDF), "application/pdf", "Synthetic.pdf");
    }

    @Test public void aNewStoreInstanceRestoresPendingBytesAndCancellationDeletesThem() throws Exception {
        PendingPdfStore first = new PendingPdfStore(temporary.getRoot());
        String token = first.save(pdf());
        PendingPdfStore recreated = new PendingPdfStore(temporary.getRoot());
        assertTrue(recreated.contains(token));
        assertArrayEquals(PDF, recreated.read(token));
        recreated.discard(token);
        assertFalse(first.contains(token));
        assertThrows(IOException.class, () -> recreated.read(token));
    }

    @Test public void opaqueTokensCannotReadOrDeleteFilesOutsideThePendingDirectory() throws Exception {
        Path outside = temporary.getRoot().toPath().resolve("private.txt");
        Files.write(outside, PDF);
        PendingPdfStore store = new PendingPdfStore(temporary.getRoot());
        for (String token : new String[] {null, "", "../private.txt", outside.toString(), "neocare-export-invalid.pdf"}) {
            assertFalse(store.contains(token));
            assertThrows(IOException.class, () -> store.read(token));
            store.discard(token);
        }
        assertArrayEquals(PDF, Files.readAllBytes(outside));
    }

    @Test public void removedOrCorruptPendingBytesFailInsteadOfProducingAnEmptyReport() throws Exception {
        PendingPdfStore store = new PendingPdfStore(temporary.getRoot());
        String token = store.save(pdf());
        Path path = temporary.getRoot().toPath().resolve("pending-reports").resolve(token);
        Files.write(path, new byte[0]);
        assertThrows(IOException.class, () -> store.read(token));
        Files.write(path, new byte[PdfPayload.MAX_BYTES + 1]);
        assertThrows(IOException.class, () -> store.read(token));
        store.discard(token);
        assertFalse(Files.exists(path));
    }

    @Test public void expiryCleansAbandonedReportsButPreservesTheRestoredExport() throws Exception {
        PendingPdfStore store = new PendingPdfStore(temporary.getRoot());
        String active = store.save(pdf());
        String abandoned = store.save(pdf());
        String recent = store.save(pdf());
        Path directory = temporary.getRoot().toPath().resolve("pending-reports");
        FileTime old = FileTime.fromMillis(System.currentTimeMillis() - 48L * 60 * 60 * 1000);
        Files.setLastModifiedTime(directory.resolve(active), old);
        Files.setLastModifiedTime(directory.resolve(abandoned), old);
        store.removeExpired(active);
        assertArrayEquals(PDF, store.read(active));
        assertFalse(store.contains(abandoned));
        assertArrayEquals(PDF, store.read(recent));
    }
}
