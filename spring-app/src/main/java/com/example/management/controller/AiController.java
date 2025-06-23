package com.example.management.controller;

import com.example.management.service.AiPredictionService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/ai")
@RequiredArgsConstructor
public class AiController {

    private final AiPredictionService aiPredictionService;

    @GetMapping("/predict")
    public ResponseEntity<String> predictLeave(
            @RequestParam String role,
            @RequestParam String leaveType,
            @RequestParam int duration
    ) {
        String result = aiPredictionService.getPrediction(role, leaveType, duration);
        return ResponseEntity.ok(result);
    }
}
