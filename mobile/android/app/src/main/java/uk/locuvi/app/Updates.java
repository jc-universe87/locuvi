package uk.locuvi.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.provider.Settings;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Locale;
import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.ResponseBody;

/**
 * New versions of the Android app: once a day (and when the owner taps Check for updates in
 * Settings), ask GitHub for the latest release. If it's newer, offer to install it: download
 * Locuvi-Android.apk, check it is exactly the released file (SHA-256 from GitHub) and signed
 * like this app, then hand it to Android's installer. Records on the phone are kept.
 */
final class Updates {
    static final String LATEST = "https://api.github.com/repos/jc-universe87/locuvi/releases/latest";
    private static final String ASSET = "Locuvi-Android.apk";
    private static final String KEY_LAST = "update_checked_at";
    private static final long DAY_MS = 24L * 3600 * 1000;
    private static final long MAX_BYTES = 200L * 1024 * 1024;
    private static final OkHttpClient HTTP = new OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .build();

    private final Activity activity;
    private final SharedPreferences prefs;
    private volatile boolean busy;
    private boolean waitingForPermission;

    Updates(Activity activity, SharedPreferences prefs) {
        this.activity = activity;
        this.prefs = prefs;
    }

    String version() {
        try {
            PackageInfo pi = activity.getPackageManager().getPackageInfo(activity.getPackageName(), 0);
            return pi.versionName == null ? "" : pi.versionName;
        } catch (PackageManager.NameNotFoundException e) {
            return "";
        }
    }

    /** "1.1.16" → [1, 1, 16]; compares number by number. */
    static int compare(String a, String b) {
        String[] x = a.replaceFirst("^v", "").split("\\.");
        String[] y = b.replaceFirst("^v", "").split("\\.");
        for (int i = 0; i < Math.max(x.length, y.length); i++) {
            int p = i < x.length ? num(x[i]) : 0;
            int q = i < y.length ? num(y[i]) : 0;
            if (p != q) {
                return Integer.compare(p, q);
            }
        }
        return 0;
    }

    private static int num(String s) {
        try {
            return Integer.parseInt(s.replaceAll("[^0-9]", ""));
        } catch (NumberFormatException e) {
            return 0;
        }
    }

    /** On opening the app: at most once a day, quietly. */
    void maybeCheck() {
        long last = prefs.getLong(KEY_LAST, 0);
        if (System.currentTimeMillis() - last > DAY_MS) {
            check(false);
        }
    }

    /** Look for a new version. {@code manual}: also say when there's none or it failed. */
    void check(boolean manual) {
        if (busy) {
            return;
        }
        busy = true;
        new Thread(() -> {
            try {
                JSONObject rel = fetchLatest();
                prefs.edit().putLong(KEY_LAST, System.currentTimeMillis()).apply();
                String latest = rel.optString("tag_name", "").replaceFirst("^v", "");
                JSONObject asset = asset(rel);
                if (asset != null && compare(latest, version()) > 0) {
                    activity.runOnUiThread(() -> offer(latest, asset));
                } else if (manual) {
                    toast(R.string.update_latest);
                }
            } catch (Exception e) {
                if (manual) {
                    toast(R.string.update_offline);
                }
            } finally {
                busy = false;
            }
        }, "locuvi-update-check").start();
    }

    private JSONObject fetchLatest() throws Exception {
        Request req = new Request.Builder().url(LATEST)
                .header("Accept", "application/vnd.github+json").build();
        try (Response res = HTTP.newCall(req).execute()) {
            ResponseBody body = res.body();
            if (!res.isSuccessful() || body == null) {
                throw new IOException("HTTP " + res.code());
            }
            return new JSONObject(body.string());
        }
    }

    private static JSONObject asset(JSONObject rel) {
        JSONArray assets = rel.optJSONArray("assets");
        if (assets == null) {
            return null;
        }
        for (int i = 0; i < assets.length(); i++) {
            JSONObject a = assets.optJSONObject(i);
            if (a != null && ASSET.equals(a.optString("name"))
                    && a.optString("digest").startsWith("sha256:")) {
                return a;
            }
        }
        return null;
    }

    private void offer(String latest, JSONObject asset) {
        if (activity.isFinishing()) {
            return;
        }
        new AlertDialog.Builder(activity)
                .setTitle(activity.getString(R.string.update_title, latest))
                .setMessage(R.string.update_message)
                .setPositiveButton(R.string.update_now, (d, w) -> download(asset))
                .setNegativeButton(R.string.update_later, null)
                .show();
    }

    private void download(JSONObject asset) {
        toast(R.string.update_downloading);
        new Thread(() -> {
            File f = ApkProvider.file(activity);
            try {
                String want = asset.getString("digest").substring("sha256:".length())
                        .toLowerCase(Locale.ROOT);
                fetchTo(asset.getString("browser_download_url"), f, want);
                if (!sameSigner(f)) {
                    f.delete();
                    activity.runOnUiThread(this::signedDifferently);
                    return;
                }
                activity.runOnUiThread(this::install);
            } catch (Exception e) {
                f.delete();
                toast(R.string.update_failed);
            }
        }, "locuvi-update-download").start();
    }

    private static void fetchTo(String url, File dest, String sha256) throws Exception {
        File dir = dest.getParentFile();
        if (dir != null && !dir.isDirectory() && !dir.mkdirs()) {
            throw new IOException("no folder");
        }
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        Request req = new Request.Builder().url(url).build(); // GitHub redirects to its file store
        try (Response res = HTTP.newCall(req).execute()) {
            ResponseBody body = res.body();
            if (!res.isSuccessful() || body == null) {
                throw new IOException("HTTP " + res.code());
            }
            long total = 0;
            try (InputStream in = body.byteStream(); FileOutputStream out = new FileOutputStream(dest)) {
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) > 0) {
                    total += n;
                    if (total > MAX_BYTES) {
                        throw new IOException("too large");
                    }
                    md.update(buf, 0, n);
                    out.write(buf, 0, n);
                }
            }
        }
        StringBuilder hex = new StringBuilder();
        for (byte b : md.digest()) {
            hex.append(String.format(Locale.ROOT, "%02x", b));
        }
        if (!hex.toString().equals(sha256)) {
            throw new IOException("not the released file");
        }
    }

    /** The new APK is signed with the same key as this app (else Android can't update it). */
    private boolean sameSigner(File apk) {
        PackageManager pm = activity.getPackageManager();
        try {
            PackageInfo mine = pm.getPackageInfo(activity.getPackageName(),
                    PackageManager.GET_SIGNING_CERTIFICATES);
            PackageInfo theirs = pm.getPackageArchiveInfo(apk.getPath(),
                    PackageManager.GET_SIGNING_CERTIFICATES);
            if (theirs == null || theirs.signingInfo == null || mine.signingInfo == null) {
                return false;
            }
            Signature[] a = mine.signingInfo.getApkContentsSigners();
            Signature[] b = theirs.signingInfo.getApkContentsSigners();
            return a.length > 0 && Arrays.equals(a, b);
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }

    private void signedDifferently() {
        new AlertDialog.Builder(activity)
                .setTitle(R.string.update_resign_title)
                .setMessage(R.string.update_resign_message)
                .setPositiveButton(R.string.update_open_page, (d, w) -> activity.startActivity(
                        new Intent(Intent.ACTION_VIEW, Uri.parse(
                                "https://github.com/jc-universe87/locuvi/blob/main/docs/APPS.md#android"))))
                .setNegativeButton(R.string.update_later, null)
                .show();
    }

    /** Back from Android's "Allow from this source" screen: carry on installing. */
    void resumed() {
        if (waitingForPermission && activity.getPackageManager().canRequestPackageInstalls()
                && ApkProvider.file(activity).isFile()) {
            waitingForPermission = false;
            install();
        }
    }

    private void install() {
        if (!activity.getPackageManager().canRequestPackageInstalls()) {
            // Android asks once: "Allow from this source" for Locuvi, then tap Update again
            toast(R.string.update_allow);
            waitingForPermission = true;
            activity.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + activity.getPackageName())));
            return;
        }
        Intent i = new Intent(Intent.ACTION_VIEW);
        i.setDataAndType(ApkProvider.uri(), "application/vnd.android.package-archive");
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        activity.startActivity(i);
    }

    private void toast(int text) {
        activity.runOnUiThread(() -> Toast.makeText(activity, text, Toast.LENGTH_LONG).show());
    }
}
