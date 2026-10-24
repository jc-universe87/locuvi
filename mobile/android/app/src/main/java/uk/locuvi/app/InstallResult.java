package uk.locuvi.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.util.Log;
import android.widget.Toast;

/** What Android's package installer says about an install Locuvi started. */
public class InstallResult extends BroadcastReceiver {
    static final String OWNER_WAITING = "owner_waiting";

    @Override
    @SuppressWarnings("deprecation") // the typed getParcelableExtra needs Android 13
    public void onReceive(Context context, Intent intent) {
        int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            // the first update: Android asks the owner (only when they asked to update)
            Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirm != null && intent.getBooleanExtra(OWNER_WAITING, false)) {
                confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(confirm);
            } else {
                // Android wanted an OK while nobody was looking: ask next time instead
                context.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE)
                        .edit().putBoolean(Updates.KEY_ASK, true).remove(Updates.KEY_LAST).apply();
            }
        } else if (status != PackageInstaller.STATUS_SUCCESS) {
            Log.w("Locuvi", "the new version wasn't installed: " + status + " "
                    + intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE));
            if (intent.getBooleanExtra(OWNER_WAITING, false)) {
                Toast.makeText(context, R.string.update_failed, Toast.LENGTH_LONG).show();
            }
        }
    }
}
