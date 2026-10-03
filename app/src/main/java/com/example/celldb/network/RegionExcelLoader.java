package com.example.celldb.network;

import android.content.ContentResolver;
import android.net.Uri;

import com.example.celldb.network.NetworkModels.NetworkData;

import java.io.InputStream;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class RegionExcelLoader {
    public interface Callback {
        void onLoaded(NetworkData data);
        void onError(Exception e);
    }

    private final ContentResolver resolver;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();

    public RegionExcelLoader(ContentResolver resolver) {
        this.resolver = resolver;
    }

    public void load(Uri uri, Callback callback) {
        worker.execute(() -> {
            try (InputStream in = resolver.openInputStream(uri)) {
                if (in == null) throw new IllegalStateException("엑셀 파일을 열 수 없습니다.");
                NetworkData data = NetworkExcelRepository.read(in);
                callback.onLoaded(data);
            } catch (Exception e) {
                callback.onError(e);
            }
        });
    }

    public void close() {
        worker.shutdownNow();
    }
}
