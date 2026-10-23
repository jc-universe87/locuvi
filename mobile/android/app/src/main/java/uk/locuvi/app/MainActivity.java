package uk.locuvi.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.util.Log;
import android.webkit.ConsoleMessage;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * Locuvi for Android.
 *
 * Normally the whole of Locuvi runs on the phone: the phone app build (frontend
 * npm run build:pocket, with the Python backend in Pyodide) ships in assets/www and is served
 * from {@link #LOCAL}, and the records stay on the phone (synced through Settings › Sync).
 * The owner can instead connect to their computer or server, whose address is kept here.
 *
 * Around the web app this adds what a WebView can't do by itself: choosing files to upload,
 * saving downloads (window.LocuviNative.saveFile), connecting to Nextcloud for sync
 * ({@link Net}), opening other websites and calendar links in the right app, and the back
 * button.
 */
public class MainActivity extends Activity {
    private static final String PREFS = "locuvi";
    private static final String KEY_SERVER = "server";
    private static final int PICK_FILES = 1;
    /** Where the bundled app is served from (never a real site; requests stay on the phone). */
    static final String LOCAL = "https://app.locuvi.local";

    private WebView web;
    private View setup;
    private EditText address;
    private TextView message;
    private ValueCallback<Uri[]> pendingFiles;
    private final Net net = new Net(); // Nextcloud sync from the phone (Net.java)
    private volatile String server; // e.g. http://192.168.1.20:8765, no trailing slash
    private volatile String pageUrl; // the page showing now; the bridge answers only our own

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setContentView(R.layout.main);
        web = findViewById(R.id.web);
        setup = findViewById(R.id.setup);
        address = findViewById(R.id.address);
        message = findViewById(R.id.message);
        Button connect = findViewById(R.id.connect);
        findViewById(R.id.use_phone).setOnClickListener(v -> usePhone());
        connect.setOnClickListener(v -> connectTo(address.getText().toString()));
        address.setOnEditorActionListener((v, actionId, event) -> {
            boolean enter = event != null && event.getKeyCode() == KeyEvent.KEYCODE_ENTER;
            if (actionId == EditorInfo.IME_ACTION_GO || enter) {
                connectTo(address.getText().toString());
                return true;
            }
            return false;
        });
        configureWebView();

        if (!handleLink(getIntent())) {
            String saved = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_SERVER, null);
            if (saved != null) {
                load(saved);
            } else {
                usePhone();
            }
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleLink(intent);
    }

    /** locuvi://connect?server=… connects straight away. */
    private boolean handleLink(Intent intent) {
        Uri data = intent == null ? null : intent.getData();
        if (data == null || !"locuvi".equals(data.getScheme())) {
            return false;
        }
        String target = data.getQueryParameter("server");
        if (target == null || target.trim().isEmpty()) {
            return false;
        }
        connectTo(target);
        return true;
    }

    // ------------------------------------------------------------------ the address

    /** "192.168.1.20:8765" → "http://192.168.1.20:8765"; null when it isn't an address. */
    static String normalise(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.isEmpty()) {
            return null;
        }
        if (!s.startsWith("http://") && !s.startsWith("https://")) {
            s = "http://" + s;
        }
        while (s.endsWith("/")) {
            s = s.substring(0, s.length() - 1);
        }
        Uri u = Uri.parse(s);
        if (u.getHost() == null || u.getHost().isEmpty()) {
            return null;
        }
        String port = u.getPort() > 0 ? ":" + u.getPort() : "";
        return u.getScheme() + "://" + u.getHost() + port;
    }

    private void connectTo(String raw) {
        String url = normalise(raw);
        if (url == null) {
            showSetup(getString(R.string.address_needed));
            return;
        }
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_SERVER, url).apply();
        load(url);
    }

    private void load(String url) {
        server = url;
        message.setVisibility(View.GONE);
        setup.setVisibility(View.GONE);
        web.setVisibility(View.VISIBLE);
        web.loadUrl(url + "/");
    }

    /** Locuvi on this phone: the bundled app, records kept here. */
    private void usePhone() {
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().remove(KEY_SERVER).apply();
        load(LOCAL);
    }

    private boolean onPhone() {
        return LOCAL.equals(server);
    }

    private void showSetup(String error) {
        web.setVisibility(View.GONE);
        setup.setVisibility(View.VISIBLE);
        String current = server != null ? server
                : getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_SERVER, "");
        if (LOCAL.equals(current)) {
            current = "";
        }
        if (current != null && address.getText().length() == 0) {
            address.setText(current.replaceFirst("^http://", ""));
        }
        if (error != null) {
            message.setText(error);
            message.setVisibility(View.VISIBLE);
        } else {
            message.setVisibility(View.GONE);
        }
    }

    private boolean isOurs(Uri uri) {
        String s = server;
        if (s == null || uri == null || uri.getScheme() == null) {
            return false;
        }
        Uri ours = Uri.parse(s);
        return uri.getScheme().equals(ours.getScheme())
                && ours.getHost() != null && ours.getHost().equalsIgnoreCase(uri.getHost())
                && uri.getPort() == ours.getPort();
    }

    // ------------------------------------------------------------------ the web view

    private void configureWebView() {
        if ((getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true); // test builds only (emulator-test.sh)
        }
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setAllowFileAccess(false);
        ws.setAllowContentAccess(false);
        ws.setMediaPlaybackRequiresUserGesture(true);
        ws.setUserAgentString(ws.getUserAgentString() + " LocuviAndroid/1.0");
        CookieManager.getInstance().setAcceptCookie(true);
        web.addJavascriptInterface(new Bridge(), "LocuviNative");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (isOurs(uri)) {
                    return false;
                }
                openElsewhere(uri); // PCSE, gov.uk, calendar links, email links…
                return true;
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view,
                                                              WebResourceRequest request) {
                Uri uri = request.getUrl();
                if ("https".equals(uri.getScheme()) && "app.locuvi.local".equals(uri.getHost())) {
                    String path = uri.getPath();
                    if (path != null && path.startsWith("/__net/") && onPhone()) {
                        return net.answer(path.substring("/__net/".length()));
                    }
                    return asset(uri);
                }
                return null;
            }

            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                pageUrl = url;
                message.setVisibility(View.GONE);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request,
                                        WebResourceError error) {
                if (request.isForMainFrame() && !onPhone()) {
                    showSetup(getString(R.string.cant_reach, server));
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage m) {
                Log.i("Locuvi", m.message()); // the phone app's own log (adb logcat -s Locuvi)
                return true;
            }

            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (pendingFiles != null) {
                    pendingFiles.onReceiveValue(null);
                }
                pendingFiles = callback;
                Intent pick = new Intent(Intent.ACTION_GET_CONTENT);
                pick.addCategory(Intent.CATEGORY_OPENABLE);
                String[] types = params.getAcceptTypes();
                pick.setType("*/*");
                if (types != null && types.length > 0 && !types[0].isEmpty()) {
                    java.util.List<String> mimes = new java.util.ArrayList<>();
                    for (String t : types) {
                        for (String part : t.split(",")) {
                            String p = part.trim();
                            if (p.contains("/")) {
                                mimes.add(p);
                            }
                        }
                    }
                    if (!mimes.isEmpty()) {
                        pick.putExtra(Intent.EXTRA_MIME_TYPES, mimes.toArray(new String[0]));
                    }
                }
                if (params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) {
                    pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                }
                try {
                    startActivityForResult(Intent.createChooser(pick, null), PICK_FILES);
                } catch (ActivityNotFoundException e) {
                    pendingFiles.onReceiveValue(null);
                    pendingFiles = null;
                    return false;
                }
                return true;
            }
        });
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode != PICK_FILES || pendingFiles == null) {
            super.onActivityResult(requestCode, resultCode, data);
            return;
        }
        Uri[] picked = null;
        if (resultCode == RESULT_OK && data != null) {
            if (data.getClipData() != null) {
                int n = data.getClipData().getItemCount();
                picked = new Uri[n];
                for (int i = 0; i < n; i++) {
                    picked[i] = data.getClipData().getItemAt(i).getUri();
                }
            } else if (data.getData() != null) {
                picked = new Uri[]{data.getData()};
            }
        }
        pendingFiles.onReceiveValue(picked);
        pendingFiles = null;
    }

    /** A file of the bundled phone app, from assets/www. */
    private WebResourceResponse asset(Uri uri) {
        String path = uri.getPath();
        if (path == null || path.equals("/") || path.isEmpty()) {
            path = "/index.html";
        }
        if (path.contains("..")) {
            return new WebResourceResponse("text/plain", "utf-8", 404, "Not found", null, null);
        }
        try {
            InputStream in = getAssets().open("www" + path);
            Map<String, String> headers = new HashMap<>();
            headers.put("Cache-Control", "no-cache");
            return new WebResourceResponse(mime(path), null, 200, "OK", headers, in);
        } catch (IOException e) {
            return new WebResourceResponse("text/plain", "utf-8", 404, "Not found", null, null);
        }
    }

    static String mime(String path) {
        String p = path.toLowerCase(Locale.ROOT);
        if (p.endsWith(".html")) return "text/html";
        if (p.endsWith(".js") || p.endsWith(".mjs")) return "text/javascript";
        if (p.endsWith(".css")) return "text/css";
        if (p.endsWith(".wasm")) return "application/wasm";
        if (p.endsWith(".json")) return "application/json";
        if (p.endsWith(".webmanifest")) return "application/manifest+json";
        if (p.endsWith(".svg")) return "image/svg+xml";
        if (p.endsWith(".png")) return "image/png";
        if (p.endsWith(".woff2")) return "font/woff2";
        if (p.endsWith(".woff")) return "font/woff";
        if (p.endsWith(".zip") || p.endsWith(".whl")) return "application/zip";
        return "application/octet-stream";
    }

    private void openElsewhere(Uri uri) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException e) {
            Toast.makeText(this, uri.toString(), Toast.LENGTH_LONG).show();
        }
    }

    @Override
    public void onBackPressed() {
        if (web.getVisibility() == View.VISIBLE && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        CookieManager.getInstance().flush();
    }

    // ------------------------------------------------------------- window.LocuviNative

    /** Called by the web app (frontend/src/lib/native.ts). Only for the connected Locuvi. */
    private class Bridge {
        private boolean fromOurs() {
            String u = pageUrl;
            return u != null && isOurs(Uri.parse(u));
        }

        @JavascriptInterface
        public void saveFile(String name, String mime, String base64) {
            if (!fromOurs()) {
                return;
            }
            byte[] bytes;
            try {
                bytes = Base64.decode(base64, Base64.DEFAULT);
            } catch (IllegalArgumentException e) {
                runOnUiThread(() -> Toast.makeText(MainActivity.this, R.string.save_failed,
                        Toast.LENGTH_LONG).show());
                return;
            }
            String safe = name == null ? "download" : name.replaceAll("[\\\\/:*?\"<>|]", "_");
            String type = mime == null || mime.isEmpty() ? "application/octet-stream" : mime;
            ContentResolver cr = getContentResolver();
            ContentValues v = new ContentValues();
            v.put(MediaStore.Downloads.DISPLAY_NAME, safe);
            v.put(MediaStore.Downloads.MIME_TYPE, type);
            v.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Locuvi");
            Uri item = cr.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
            if (item == null) {
                runOnUiThread(() -> Toast.makeText(MainActivity.this, R.string.save_failed,
                        Toast.LENGTH_LONG).show());
                return;
            }
            try (OutputStream out = cr.openOutputStream(item)) {
                if (out == null) {
                    throw new java.io.IOException("no output stream");
                }
                out.write(bytes);
            } catch (java.io.IOException e) {
                cr.delete(item, null, null);
                runOnUiThread(() -> Toast.makeText(MainActivity.this, R.string.save_failed,
                        Toast.LENGTH_LONG).show());
                return;
            }
            runOnUiThread(() -> {
                Toast.makeText(MainActivity.this, getString(R.string.saved_to, safe),
                        Toast.LENGTH_SHORT).show();
                Intent view = new Intent(Intent.ACTION_VIEW);
                view.setDataAndType(item, type);
                view.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                try {
                    startActivity(view);
                } catch (ActivityNotFoundException e) {
                    Toast.makeText(MainActivity.this, R.string.no_viewer, Toast.LENGTH_LONG).show();
                }
            });
        }

        @JavascriptInterface
        public void changeServer() {
            if (!fromOurs()) {
                return;
            }
            runOnUiThread(() -> {
                getSharedPreferences(PREFS, MODE_PRIVATE).edit().remove(KEY_SERVER).apply();
                web.loadUrl("about:blank");
                web.clearHistory();
                address.setText("");
                showSetup(null);
            });
        }

        /** A connection the engine on this phone asks for (see {@link Net}). */
        @JavascriptInterface
        public void netStash(String id, String request) {
            if (!fromOurs() || !onPhone() || id == null || request == null) {
                return;
            }
            net.stash(id, request);
        }

        @JavascriptInterface
        public String serverUrl() {
            return server == null || onPhone() ? "" : server;
        }
    }
}
