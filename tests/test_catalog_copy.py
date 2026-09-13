import unittest
from decimal import Decimal

from catalog_copy import imported_description, presentation
from domain import Service, family_for


class CatalogCopyTests(unittest.TestCase):
    def test_internal_category_does_not_override_product_type(self):
        self.assertEqual(family_for("IG - Curtidas Brasileiras", "API Seguidor82"), "Curtidas/Reações")
        self.assertEqual(family_for("IG - Comentários Brasileiros", "Seguidores"), "Comentários")
    def parse(self, identity, name, category="Serviços Streaming"):
        return Service.parse({"service":identity,"name":name,"category":category,
                              "type":"Package","rate":"15.90","min":1,"max":1})

    def test_full_names_and_subscription_classification(self):
        item = self.parse(707, "YT Premium + Cv PRO | Combo | Link de Convite")
        self.assertEqual(item.platform,"Streaming e Apps")
        self.assertEqual(item.family,"Combos")
        self.assertIn("YouTube Premium + Canva Pro",item.name)
        self.assertEqual(item.rate,Decimal("15.90"))

    def test_reused_id_does_not_inherit_brand(self):
        item = self.parse(721,"Produto novo")
        self.assertNotIn("Netflix",item.name)
        self.assertEqual(imported_description(721,"Produto novo"),"")

    def test_imported_manual_delivery_preserves_shared_access(self):
        item = self.parse(721,"⭕Ntx  Plano 30 Dias | Plano Mensal | Tela Privada |")
        info = presentation(item)
        self.assertTrue(info["manualDelivery"])
        self.assertIn("compartilhada", info["details"])
        self.assertNotIn("WhatsApp",info["details"])
        self.assertNotIn("soupopular",info["details"].lower())

    def test_empty_description_does_not_invent_delivery_promise(self):
        item = self.parse(910,"DN plus plano 30 Dias | Tela Privada |")
        info = presentation(item)
        self.assertIn("Disney+",info["displayName"])
        self.assertIn("não foram informadas",info["details"])
        self.assertFalse(info["manualDelivery"])
