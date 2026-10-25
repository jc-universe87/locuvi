package uk.locuvi.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.InstallSourceInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
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
 * Settings), ask GitHub for the latest release. A newer Locuvi-Android.apk is downloaded and
 * checked: exactly the released file (SHA-256 from GitHub) and signed like this app. Then it
 * goes to Android's package installer. Records on the phone are kept.
 *
 * Android 12 and newer let an app update itself without asking, once it installed the copy
 * that's there. So the first update asks (one tap on Update, then Android's Install), and
 * every one after that installs by itself once Locuvi has been out of sight for a couple of
 * minutes; the next time it's opened, it's new.
 */
final class Updates {
    static final String LATEST = "https://api.github.com/repos/pistio/locuvi/releases/latest";
    private static final String ASSET = "Locuvi-Android.apk";
    static final String KEY_LAST = "update_checked_at";
    static final String KEY_ASK = "update_ask_next"; // a quiet install needed the owner's OK
    private static final long DAY_MS = 24L * 3600 * 1000;
    private static final long MAX_BYTES = 200L * 1024 * 1024;
    private static final long QUIET_MS = 2L * 60 * 1000; // out of sight this long: install
    private static final String TAG = "Locuvi";
    private static final OkHttpClient HTTP = new OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .build();

    private final Activity activity;
    private final SharedPreferences prefs;
    private volatile boolean busy;
    private boolean waitingForPermission;
    private volatile boolean readyToInstall; // downloaded and checked, waiting for a quiet moment
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable installQuietly = this::installNow;

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

    static File file(Context c) {
        return new File(new File(c.getCacheDir(), "updates"), "Locuvi.apk");
    }

    /** Can this update install without asking? Android 12+, and Locuvi installed this copy. */
    private boolean bySelf() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            return false;
        }
        try {
            InstallSourceInfo src = activity.getPackageManager()
                    .getInstallSourceInfo(activity.getPackageName());
            return activity.getPackageName().equals(src.getInstallingPackageName())
                    && activity.getPackageManager().canRequestPackageInstalls();
        } catch (PackageManager.NameNotFoundException e) {
            return false;
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
                    if (!manual && bySelf() && !prefs.getBoolean(KEY_ASK, false)) {
                        download(asset, false); // installs by itself once out of sight
                    } else {
                        activity.runOnUiThread(() -> offer(latest, asset));
                    }
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
        prefs.edit().remove(KEY_ASK).apply();
        new AlertDialog.Builder(activity)
                .setTitle(activity.getString(R.string.update_title, latest))
                .setMessage(R.string.update_message)
                .setPositiveButton(R.string.update_now, (d, w) -> download(asset, true))
                .setNegativeButton(R.string.update_later, null)
                .show();
    }

    /** {@code now}: the owner tapped Update, so install straight away (else when quiet). */
    private void download(JSONObject asset, boolean now) {
        if (now) {
            toast(R.string.update_downloading);
        }
        new Thread(() -> {
            File f = file(activity);
            try {
                String want = asset.getString("digest").substring("sha256:".length())
                        .toLowerCase(Locale.ROOT);
                fetchTo(asset.getString("browser_download_url"), f, want);
                if (!sameSigner(f)) {
                    f.delete();
                    activity.runOnUiThread(this::signedDifferently);
                    return;
                }
                if (now) {
                    activity.runOnUiThread(this::install);
                } else {
                    readyToInstall = true;
                    Log.i(TAG, "a new version is ready: it installs when Locuvi is out of sight");
                }
            } catch (Exception e) {
                f.delete();
                if (now) {
                    toast(R.string.update_failed);
                }
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
                                "https://github.com/pistio/locuvi/blob/main/docs/APPS.md#android"))))
                .setNegativeButton(R.string.update_later, null)
                .show();
    }

    /** Back from Android's "Allow from this source" screen: carry on installing. */
    void resumed() {
        main.removeCallbacks(installQuietly);
        if (waitingForPermission && activity.getPackageManager().canRequestPackageInstalls()
                && file(activity).isFile()) {
            waitingForPermission = false;
            install();
        }
    }

    /** Locuvi went out of sight: a ready update installs if it stays that way for a bit. */
    void stopped() {
        if (readyToInstall) {
            main.postDelayed(installQuietly, QUIET_MS);
        }
    }

    private void installNow() {
        if (readyToInstall && file(activity).isFile()) {
            readyToInstall = false;
            Log.i(TAG, "installing the new version while Locuvi is out of sight");
            commit(false);
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
        if (bySelf()) {
            toast(R.string.update_closing);
        }
        commit(true);
    }

    /**
     * Hand the checked APK to Android's package installer. If Android needs the owner's OK
     * (the first time), it says so to {@link InstallResult}, which shows Android's screen.
     */
    private void commit(boolean ownerWaiting) {
        File f = file(activity);
        PackageInstaller pi = activity.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams params =
                new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        params.setAppPackageName(activity.getPackageName());
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED);
        }
        try {
            int id = pi.createSession(params);
            try (PackageInstaller.Session session = pi.openSession(id)) {
                try (InputStream in = new FileInputStream(f);
                     OutputStream out = session.openWrite("Locuvi.apk", 0, f.length())) {
                    byte[] buf = new byte[65536];
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        out.write(buf, 0, n);
                    }
                    session.fsync(out);
                }
                Intent result = new Intent(activity, InstallResult.class)
                        .putExtra(InstallResult.OWNER_WAITING, ownerWaiting);
                PendingIntent pending = PendingIntent.getBroadcast(activity, id, result,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE);
                session.commit(pending.getIntentSender());
            }
        } catch (IOException | RuntimeException e) {
            Log.w(TAG, "the new version couldn't be handed to Android", e);
            if (ownerWaiting) {
                toast(R.string.update_failed);
            }
        }
    }

    private void toast(int text) {
        activity.runOnUiThread(() -> Toast.makeText(activity, text, Toast.LENGTH_LONG).show());
    }
}
