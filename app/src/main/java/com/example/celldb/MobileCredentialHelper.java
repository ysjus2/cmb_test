package com.example.celldb;

import android.app.Activity;
import android.os.CancellationSignal;

import androidx.annotation.NonNull;
import androidx.credentials.CreateCredentialResponse;
import androidx.credentials.CreatePasswordRequest;
import androidx.credentials.Credential;
import androidx.credentials.CredentialManager;
import androidx.credentials.CredentialManagerCallback;
import androidx.credentials.GetCredentialRequest;
import androidx.credentials.GetCredentialResponse;
import androidx.credentials.GetPasswordOption;
import androidx.credentials.PasswordCredential;
import androidx.credentials.exceptions.CreateCredentialException;
import androidx.credentials.exceptions.GetCredentialException;

final class MobileCredentialHelper {
    interface LoginCallback {
        void onCredential(String username, String password);
        void onUnavailable();
    }

    private MobileCredentialHelper() {}

    static void requestSavedLogin(Activity activity, LoginCallback callback) {
        CredentialManager manager = CredentialManager.create(activity);
        GetCredentialRequest request = new GetCredentialRequest.Builder()
                .addCredentialOption(new GetPasswordOption())
                .build();

        manager.getCredentialAsync(
                activity,
                request,
                new CancellationSignal(),
                activity.getMainExecutor(),
                new CredentialManagerCallback<GetCredentialResponse, GetCredentialException>() {
                    @Override
                    public void onResult(@NonNull GetCredentialResponse result) {
                        Credential credential = result.getCredential();
                        if (credential instanceof PasswordCredential) {
                            PasswordCredential password = (PasswordCredential) credential;
                            callback.onCredential(password.getId(), password.getPassword());
                        } else {
                            callback.onUnavailable();
                        }
                    }

                    @Override
                    public void onError(@NonNull GetCredentialException error) {
                        callback.onUnavailable();
                    }
                }
        );
    }

    static void offerSaveLogin(Activity activity, String username, String password) {
        if (username == null || username.trim().isEmpty()
                || password == null || password.isEmpty()) return;

        CredentialManager manager = CredentialManager.create(activity);
        CreatePasswordRequest request = new CreatePasswordRequest(
                username.trim(),
                password,
                null,
                false,
                false
        );

        manager.createCredentialAsync(
                activity,
                request,
                new CancellationSignal(),
                activity.getMainExecutor(),
                new CredentialManagerCallback<CreateCredentialResponse, CreateCredentialException>() {
                    @Override public void onResult(@NonNull CreateCredentialResponse result) {}
                    @Override public void onError(@NonNull CreateCredentialException error) {}
                }
        );
    }
}
