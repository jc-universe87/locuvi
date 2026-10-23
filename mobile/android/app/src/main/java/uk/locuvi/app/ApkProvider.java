package uk.locuvi.app;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * Hands the downloaded update (and nothing else) to Android's package installer, which can
 * only open it through a content:// address. Not exported: only apps this app grants a
 * single read permission to (the installer, for one install) can open it.
 */
public class ApkProvider extends ContentProvider {
    static final String AUTHORITY = "uk.locuvi.app.updates";
    static final String NAME = "Locuvi.apk";

    static File file(android.content.Context c) {
        return new File(new File(c.getCacheDir(), "updates"), NAME);
    }

    static Uri uri() {
        return Uri.parse("content://" + AUTHORITY + "/" + NAME);
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!("/" + NAME).equals(uri.getPath()) || !"r".equals(mode)) {
            throw new FileNotFoundException();
        }
        return ParcelFileDescriptor.open(file(getContext()), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override
    public String getType(Uri uri) {
        return "application/vnd.android.package-archive";
    }

    @Override
    public Cursor query(Uri u, String[] p, String s, String[] a, String o) {
        return null;
    }

    @Override
    public Uri insert(Uri u, ContentValues v) {
        return null;
    }

    @Override
    public int delete(Uri u, String s, String[] a) {
        return 0;
    }

    @Override
    public int update(Uri u, ContentValues v, String s, String[] a) {
        return 0;
    }
}
