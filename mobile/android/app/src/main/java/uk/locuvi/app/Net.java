package uk.locuvi.app;

import android.util.Base64;
import android.webkit.WebResourceResponse;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InterruptedIOException;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import javax.net.ssl.SSLException;

import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;

/**
 * Connections the Locuvi engine on the phone asks for (Nextcloud sync, WebDAV).
 *
 * The engine runs in a Web Worker, where the page can't reach Java directly and the browser
 * would apply its cross-site rules (CORS) and block http:// addresses. So the worker hands the
 * request to the page, the page passes it here ({@link #stash}), and the worker then loads
 * https://app.locuvi.local/__net/&lt;id&gt;, which {@link #answer} serves with Nextcloud's reply.
 * Requests come only from the bundled app (MainActivity checks), and redirects are never
 * followed, so the app password never goes to another address.
 */
final class Net {
    private static final long WAIT_MS = 15_000;
    private static final int MAX_BYTES = 60 * 1024 * 1024;
    private static final OkHttpClient CLIENT = new OkHttpClient.Builder()
            .followRedirects(false)
            .followSslRedirects(false)
            .retryOnConnectionFailure(false)
            .build();
    private static final java.util.Set<String> NEEDS_BODY = new java.util.HashSet<>(
            java.util.Arrays.asList("POST", "PUT", "PATCH", "PROPPATCH", "REPORT"));
    private final Map<String, String> waiting = new HashMap<>();

    /** The page passes on a request from the engine: JSON {method, url, headers, body, timeout}. */
    void stash(String id, String request) {
        synchronized (waiting) {
            if (waiting.size() > 50) {
                waiting.clear(); // never answered: the engine has moved on
            }
            waiting.put(id, request);
            waiting.notifyAll();
        }
    }

    /** The worker's /__net/&lt;id&gt; request: make the connection, answer with the reply. */
    WebResourceResponse answer(String id) {
        String request = take(id);
        JSONObject meta = new JSONObject();
        byte[] body = new byte[0];
        try {
            if (request == null) {
                meta.put("error", "unreachable");
            } else {
                body = send(new JSONObject(request), meta);
            }
        } catch (JSONException e) {
            body = new byte[0];
        }
        Map<String, String> headers = new HashMap<>();
        headers.put("Cache-Control", "no-store");
        headers.put("X-Locuvi-Net", Base64.encodeToString(
                meta.toString().getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP));
        return new WebResourceResponse("application/octet-stream", null, 200, "OK", headers,
                new ByteArrayInputStream(body));
    }

    private String take(String id) {
        long until = System.currentTimeMillis() + WAIT_MS;
        synchronized (waiting) {
            while (!waiting.containsKey(id)) {
                long left = until - System.currentTimeMillis();
                if (left <= 0) {
                    return null;
                }
                try {
                    waiting.wait(left);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return null;
                }
            }
            return waiting.remove(id);
        }
    }

    private static byte[] send(JSONObject req, JSONObject meta) throws JSONException {
        String method = req.getString("method").toUpperCase(Locale.ROOT);
        String url = req.getString("url");
        if (!url.startsWith("https://") && !url.startsWith("http://")) {
            meta.put("error", "unreachable");
            return new byte[0];
        }
        String b64 = req.optString("body", "");
        byte[] data = b64.isEmpty() ? null : Base64.decode(b64, Base64.DEFAULT);
        Request.Builder rb = new Request.Builder().url(url);
        JSONArray headers = req.optJSONArray("headers");
        String type = null;
        if (headers != null) {
            for (int i = 0; i < headers.length(); i++) {
                JSONArray h = headers.getJSONArray(i);
                String name = h.getString(0);
                if (name.equalsIgnoreCase("content-type")) {
                    type = h.getString(1);
                }
                rb.addHeader(name, h.getString(1));
            }
        }
        RequestBody rbody = null;
        if (data != null || NEEDS_BODY.contains(method)) {
            MediaType mt = type == null ? null : MediaType.parse(type);
            rbody = RequestBody.create(data == null ? new byte[0] : data, mt);
        }
        rb.method(method, rbody);
        long timeout = Math.max(1000, req.optLong("timeout", 20_000));
        OkHttpClient client = CLIENT.newBuilder()
                .callTimeout(timeout * 3, TimeUnit.MILLISECONDS)
                .connectTimeout(timeout, TimeUnit.MILLISECONDS)
                .readTimeout(timeout, TimeUnit.MILLISECONDS)
                .writeTimeout(timeout, TimeUnit.MILLISECONDS)
                .build();
        try (Response res = client.newCall(rb.build()).execute()) {
            JSONArray out = new JSONArray();
            for (int i = 0; i < res.headers().size(); i++) {
                out.put(new JSONArray().put(res.headers().name(i)).put(res.headers().value(i)));
            }
            ResponseBody rbo = res.body();
            byte[] bytes = rbo == null ? new byte[0] : rbo.bytes();
            if (bytes.length > MAX_BYTES) {
                meta.put("error", "too_large");
                return new byte[0];
            }
            meta.put("status", res.code());
            meta.put("headers", out);
            return bytes;
        } catch (SocketTimeoutException | InterruptedIOException e) {
            meta.put("error", "timeout");
        } catch (SSLException e) {
            meta.put("error", "tls");
        } catch (IOException | IllegalArgumentException e) {
            meta.put("error", "unreachable");
        }
        return new byte[0];
    }
}
