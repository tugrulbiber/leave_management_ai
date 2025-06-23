package com.example.management.service;

import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.HashMap;
import java.util.Map;

@Service
public class AiPredictionService {

    private final RestTemplate restTemplate = new RestTemplate();

    public String getPrediction(String role, String leaveType, int duration) {
        String url = "http://localhost:5000/predict";

        // JSON Body
        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("role", role);
        requestBody.put("leave_type", leaveType);
        requestBody.put("duration", duration);

        // Header
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);

        // İstek
        HttpEntity<Map<String, Object>> requestEntity = new HttpEntity<>(requestBody, headers);

        // Yanıt
        ResponseEntity<Map> response = restTemplate.postForEntity(url, requestEntity, Map.class);

        if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
            return response.getBody().get("prediction").toString();  // örn: "APPROVED"
        } else {
            return "Tahmin yapılamadı";
        }
    }
}
