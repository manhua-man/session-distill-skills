#!/usr/bin/env python3
"""Contract and unit tests for AutoVerifier and CodebaseIndex."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

# Add shared to path
REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_DIR = REPO_ROOT / "shared"
import sys

if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from distill_core.auto_verify import AutoVerifier, CodebaseIndex, VerificationResult


class TestAutoVerifier(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root / "src"
        self.mig = self.root / "migrations"
        self.src.mkdir(parents=True)
        self.mig.mkdir(parents=True)

        (self.src / "order.service.ts").write_text(
            "export class OrderService {\n"
            "  async createOrder(userId: string) { return 'ord_1'; }\n"
            "}\n",
            encoding="utf-8",
        )
        (self.src / "order.controller.ts").write_text(
            "@Controller('orders')\n"
            "export class OrderController {\n"
            "  @Post('create')\n"
            "  async create() {}\n"
            "}\n",
            encoding="utf-8",
        )
        (self.src / "constants.ts").write_text(
            "export const MAX_ORDER_LIMIT = 50;\n"
            "export const DEFAULT_TIMEOUT = '30s';\n",
            encoding="utf-8",
        )
        (self.mig / "1785000000000-CreateOrderTable.ts").write_text(
            "export class CreateOrderTable1785000000000 {}\n",
            encoding="utf-8",
        )

        self.verifier = AutoVerifier(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_file_exists(self) -> None:
        res = self.verifier.verify_claim("order.service.ts 文件存在")
        self.assertEqual(res.status, "ANSWERED")
        self.assertEqual(res.rule_type, "FILE_EXISTS")
        self.assertEqual(res.evidence, "src/order.service.ts:L1")

    def test_symbol_grep(self) -> None:
        res = self.verifier.verify_claim("OrderService 核心服务类")
        self.assertEqual(res.status, "ANSWERED")
        self.assertEqual(res.rule_type, "SYMBOL_GREP")
        self.assertIn("src/order.service.ts", res.evidence)

    def test_member_access(self) -> None:
        res = self.verifier.verify_claim("OrderService.createOrder 处理订单创建")
        self.assertEqual(res.status, "ANSWERED")
        self.assertEqual(res.rule_type, "SYMBOL_GREP")
        self.assertIn("OrderService.createOrder", res.answer)

    def test_route_endpoint(self) -> None:
        res = self.verifier.verify_claim("POST /orders/create 创建订单接口")
        self.assertEqual(res.status, "ANSWERED")
        self.assertEqual(res.rule_type, "ROUTE_ENDPOINT")
        self.assertIn("src/order.controller.ts", res.evidence)

    def test_config_value(self) -> None:
        res = self.verifier.verify_claim("常量 MAX_ORDER_LIMIT=50")
        self.assertEqual(res.status, "ANSWERED")
        self.assertEqual(res.rule_type, "CONFIG_VALUE")
        self.assertIn("MAX_ORDER_LIMIT=50", res.answer)

    def test_migration(self) -> None:
        res = self.verifier.verify_claim("迁移 1785000000000-CreateOrderTable.ts 已落地")
        self.assertEqual(res.status, "ANSWERED")
        self.assertEqual(res.rule_type, "MIGRATION")
        self.assertEqual(res.evidence, "migrations/1785000000000-CreateOrderTable.ts:L1")

    def test_unverified_fallback(self) -> None:
        res = self.verifier.verify_claim("一些不存在的业务假设或无依据讨论")
        self.assertEqual(res.status, "PENDING")
        self.assertEqual(res.rule_type, "UNVERIFIED")

    def test_verify_answer_packet_apply(self) -> None:
        packet = self.root / "packet.md"
        packet.write_text(
            "# Answer Packet: test-session\n\n"
            "## Claims extracted (hypotheses)\n\n"
            "1. order.service.ts 文件存在\n"
            "2. 未知未验证假设条目\n\n"
            "## Results\n\n"
            "| ID | Lens | Status | Answer | Evidence |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| Q1 | repo | PENDING | | |\n"
            "| Q2 | repo | PENDING | | |\n\n"
            "## Promotion gate\n",
            encoding="utf-8",
        )

        res = self.verifier.verify_answer_packet(packet, apply=True)
        self.assertEqual(res["total_questions"], 2)
        self.assertEqual(res["auto_verified"], 1)
        self.assertTrue(res["applied"])

        content = packet.read_text(encoding="utf-8")
        self.assertIn("| Q1 | payment | ANSWERED | Verified file exists: order.service.ts | src/order.service.ts:L1 |", content)
        self.assertIn("| Q2 | repo | PENDING |", content)

    def test_self_test(self) -> None:
        self.assertTrue(AutoVerifier.self_test())


if __name__ == "__main__":
    unittest.main()
