package com.example.celldb;

import org.junit.Test;
import static org.junit.Assert.*;

public class ServerErrorTest {
    @Test public void classifiesFailuresWithoutExposingSensitiveMessages() {
        String secret="password=secret access_token=secret refresh_token=secret";
        Throwable[] errors={new javax.net.ssl.SSLHandshakeException(secret),new java.net.SocketTimeoutException(secret),new java.net.ConnectException(secret),new org.json.JSONException(secret)};
        String[] categories={"TLS certificate error","connection timeout","connection refused","JSON parsing error"};
        for(int i=0;i<errors.length;i++) {
            assertEquals(categories[i],ServerError.category(new Exception(secret,errors[i])));
            assertFalse(ServerError.userMessage(errors[i]).contains("secret"));
        }
        for(int status:new int[]{401,403,404,422,500})assertEquals("HTTP "+status,ServerError.category(new ServerApiClient.ApiError(status,"안전한 메시지")));
    }
}
