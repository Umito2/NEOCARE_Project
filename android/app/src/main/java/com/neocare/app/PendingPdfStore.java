package com.neocare.app;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.UUID;
import java.util.regex.Pattern;

/** Temporary private storage while Android's document picker owns the screen. */
final class PendingPdfStore {
    private static final Pattern TOKEN = Pattern.compile(
            "neocare-export-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\.pdf");
    private static final long DAY_MILLIS = 24L * 60 * 60 * 1000;
    private final Path directory;

    PendingPdfStore(File cacheDirectory) {
        directory = cacheDirectory.toPath().resolve("pending-reports");
    }

    String save(PdfPayload pdf) throws IOException {
        Files.createDirectories(directory);
        String token = "neocare-export-" + UUID.randomUUID() + ".pdf";
        Path path = path(token);
        try {
            Files.write(path, pdf.bytes, java.nio.file.StandardOpenOption.CREATE_NEW,
                    java.nio.file.StandardOpenOption.WRITE);
            return token;
        } catch (IOException failure) {
            discard(token);
            throw failure;
        }
    }

    boolean contains(String token) {
        Path path = path(token);
        return path != null && Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS);
    }

    byte[] read(String token) throws IOException {
        Path path = path(token);
        if (path == null || !Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) {
            throw new IOException("The pending report is unavailable");
        }
        try (InputStream input = Files.newInputStream(path);
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (output.size() + count > PdfPayload.MAX_BYTES) throw new IOException("Invalid pending report");
                output.write(buffer, 0, count);
            }
            byte[] bytes = output.toByteArray();
            if (bytes.length < 5 || bytes[0] != '%' || bytes[1] != 'P'
                    || bytes[2] != 'D' || bytes[3] != 'F' || bytes[4] != '-') {
                throw new IOException("Invalid pending report");
            }
            return bytes;
        }
    }

    void discard(String token) {
        Path path = path(token);
        if (path == null) return;
        try {
            Files.deleteIfExists(path);
        } catch (IOException ignored) {
            // A later launch retries expiry cleanup; never expose private paths.
        }
    }

    void removeExpired(String activeToken) {
        File[] files = directory.toFile().listFiles();
        if (files == null) return;
        long cutoff = System.currentTimeMillis() - DAY_MILLIS;
        for (File file : files) {
            String token = file.getName();
            if (TOKEN.matcher(token).matches() && !token.equals(activeToken) && file.lastModified() < cutoff) {
                discard(token);
            }
        }
    }

    private Path path(String token) {
        return token != null && TOKEN.matcher(token).matches() ? directory.resolve(token) : null;
    }
}
