package com.example.celldb;

import java.net.ConnectException;
import java.net.SocketTimeoutException;
import javax.net.ssl.SSLException;
import org.json.JSONException;

/** Never log exception bodies: they can contain server data or credentials. */
final class ServerError {
    static String category(Throwable error) {
        for(Throwable cause=error;cause!=null;cause=cause.getCause()) {
            if(cause instanceof ServerApiClient.ApiError)return "HTTP "+((ServerApiClient.ApiError)cause).status;
            if(cause instanceof SSLException || cause instanceof java.security.cert.CertificateException)return "TLS certificate error";
            if(cause instanceof SocketTimeoutException)return "connection timeout";
            if(cause instanceof ConnectException)return "connection refused";
            if(cause instanceof JSONException || cause instanceof ClassCastException)return "JSON parsing error";
        }
        return "network error";
    }
    static String userMessage(Throwable error) {
        String category=category(error);
        if(category.equals("TLS certificate error"))return "서버 인증서를 확인할 수 없습니다. 관리자에게 문의하세요.";
        if(category.equals("connection timeout"))return "서버 연결 시간이 초과됐습니다. 회사 네트워크 연결을 확인하세요.";
        if(category.equals("connection refused"))return "서버에 연결할 수 없습니다. 서버 상태를 확인하세요.";
        if(category.equals("JSON parsing error"))return "서버 응답 형식이 올바르지 않습니다. 관리자에게 문의하세요.";
        if(category.equals("HTTP 404"))return "요청한 서버 기능 또는 자료를 찾을 수 없습니다.";
        if(category.equals("HTTP 422"))return "입력 정보를 확인하세요.";
        if(category.startsWith("HTTP 5"))return "서버 처리 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.";
        if(error instanceof ServerApiClient.ApiError)return error.getMessage();
        return "회사 네트워크 연결과 서버 상태를 확인하세요.";
    }
}
