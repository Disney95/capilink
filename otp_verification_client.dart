// CapiLink — Verificación de OTP en el dispositivo del agente (100% offline)
// Ver ARCHITECTURE.md §4. Requiere el paquete `crypto` (pub.dev/packages/crypto).

import 'dart:convert';
import 'dart:typed_data';
import 'package:crypto/crypto.dart';

class OtpVerificationResult {
  final bool success;
  final String reason; // 'OK' | 'MISMATCH' | 'EXPIRED' | 'LOCKED'
  const OtpVerificationResult(this.success, this.reason);
}

class OtpVerifier {
  /// Calcula HMAC-SHA256(key = orderSecret, message = otp) y compara en
  /// tiempo constante contra el hash almacenado localmente. No requiere
  /// red: toda la información necesaria ya viajó con la orden al
  /// sincronizar (otp_hash + otp_secret), nunca el OTP en texto plano.
  static String _computeHmac(String orderSecretHex, String otp) {
    final key = _hexToBytes(orderSecretHex);
    final hmacSha256 = Hmac(sha256, key);
    final digest = hmacSha256.convert(utf8.encode(otp));
    return digest.toString(); // hex
  }

  static Uint8List _hexToBytes(String hex) {
    final result = Uint8List(hex.length ~/ 2);
    for (var i = 0; i < hex.length; i += 2) {
      result[i ~/ 2] = int.parse(hex.substring(i, i + 2), radix: 16);
    }
    return result;
  }

  /// Comparación en tiempo constante — evita timing attacks al comparar
  /// dos hex strings de igual longitud esperada.
  static bool _constantTimeEquals(String a, String b) {
    if (a.length != b.length) return false;
    var result = 0;
    for (var i = 0; i < a.length; i++) {
      result |= a.codeUnitAt(i) ^ b.codeUnitAt(i);
    }
    return result == 0;
  }

  /// [order] es la fila local de distribution_orders ya sincronizada.
  /// [enteredOtp] es lo que el destinatario dictó verbalmente al agente.
  ///
  /// Efectos secundarios esperados por quien llama esta función:
  /// - Si devuelve MISMATCH: incrementar y PERSISTIR otp_attempts
  ///   ANTES de mostrar el resultado (para que un corte de energía a
  ///   mitad de intento no regale un intento gratis).
  /// - Si devuelve OK: marcar la orden DELIVERED dentro de la misma
  ///   transacción que inserta la fila en `deliveries` y en `sync_queue`
  ///   (ver el bloque BEGIN IMMEDIATE...COMMIT en schema_sqlite_client.sql).
  static OtpVerificationResult verify({
    required String otpHash,
    required String otpSecretHex,
    required DateTime otpExpiresAt,
    required int otpAttempts,
    required int otpMaxAttempts,
    required String enteredOtp,
  }) {
    if (otpAttempts >= otpMaxAttempts) {
      return const OtpVerificationResult(false, 'LOCKED');
    }
    if (DateTime.now().toUtc().isAfter(otpExpiresAt.toUtc())) {
      return const OtpVerificationResult(false, 'EXPIRED');
    }

    final candidate = _computeHmac(otpSecretHex, enteredOtp.trim());
    final match = _constantTimeEquals(candidate, otpHash);

    return match
        ? const OtpVerificationResult(true, 'OK')
        : const OtpVerificationResult(false, 'MISMATCH');
  }
}
