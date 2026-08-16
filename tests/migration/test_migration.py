import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("migration_validation", ROOT / "tools/migrate/validate_migration.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MIGRATE_SPEC = importlib.util.spec_from_file_location("p0_migration", ROOT / "tools/migrate/migrate_v24_to_p0.py")
MIGRATE = importlib.util.module_from_spec(MIGRATE_SPEC)
MIGRATE_SPEC.loader.exec_module(MIGRATE)


class MigrationContractTests(unittest.TestCase):
    def test_explicit_urgent_claim_does_not_enter_normal_asking_line(self):
        self.assertEqual("urgent_sale", MIGRATE.normalize_history_price_type("asking", "急售國際服帳號"))
        self.assertEqual("urgent_sale", MIGRATE.normalize_history_price_type("normal_listing", "急出國際服帳號"))
        self.assertEqual("asking", MIGRATE.normalize_history_price_type("asking", "一般售帳"))
        self.assertEqual("sold_claim", MIGRATE.normalize_history_price_type("sold_explicit", "急售後已售"))

    def test_formal_urgent_listings_normalize_at_each_market_layer(self):
        # These texts are the four formally identified regressions.  The
        # migration must apply the same rule before source, normalized, and
        # history records are written, rather than fixing only the history.
        formal_listings = {
            "listing_0716": "#售 #代友售 #急售；開價 NTD 2500。",
            "listing_0965": "#售號／#無翼號／#急出：開價 14000 台幣可小刀。",
            "listing_1014": "急售帳號，開價 1,000 台幣。",
            "listing_1018": "急售魔法季大斷帳號，開價 10,000 台幣。",
        }
        for listing_id, listing_text in formal_listings.items():
            with self.subTest(listing_id=listing_id):
                source_price_type = MIGRATE.normalize_urgent_listing_price_type("asking", listing_text)
                normalized_price_type = MIGRATE.normalize_urgent_listing_price_type(source_price_type, listing_text)
                history_price_type = MIGRATE.normalize_history_price_type("asking", listing_text)
                self.assertEqual("urgent_sale", source_price_type)
                self.assertEqual("urgent_sale", normalized_price_type)
                self.assertEqual("urgent_sale", history_price_type)

    def test_plain_sale_word_does_not_imply_urgent_and_sold_claim_is_preserved(self):
        self.assertEqual("asking", MIGRATE.normalize_market_price_type("asking", "出售帳號，開價 2500 台幣"))
        self.assertEqual("normal_listing", MIGRATE.normalize_market_price_type("normal_listing", "一般出售帳號"))
        self.assertEqual("sold_claim", MIGRATE.normalize_market_price_type("sold_explicit", "急出後已售"))

    def test_urgent_price_variant_is_consistent_with_parent_listing(self):
        variants = MIGRATE.normalize_price_variants(
            [{"kind": "asking", "amount_twd": 14000}, {"kind": "sold_explicit", "amount_twd": 12000}],
            "#急出 開價 14000；已售聲稱 12000",
        )
        self.assertEqual("urgent_sale", variants[0]["kind"])
        self.assertEqual("sold_explicit", variants[1]["kind"])

    def test_brokerage_included_price_preserves_urgent_semantics_but_requires_review(self):
        review = MIGRATE.price_semantic_review("急售國際服帳號；售價 18000 台幣（含仲）", "urgent_sale")
        self.assertEqual(review, {
            "urgency": "urgent_sale", "brokerage_included": True,
            "evidence_state": "text_claim", "review_status": "needs_review",
            "reason_codes": ["brokerage_included_price"],
        })
        self.assertIsNone(MIGRATE.price_semantic_review("急售國際服帳號；售價 18000 台幣", "urgent_sale"))

    def test_snapshot_counts_dates_and_privacy(self):
        result = MODULE.validate(ROOT)
        self.assertTrue(result["valid"], result)
        self.assertEqual(5, result["verified_history_dates"])
        self.assertEqual([], result["forbidden_identity_keys"])

    def test_season_range_is_conservative_and_tracks_gaps(self):
        aliases = {"表演": "season_performance", "破曉": "season_shattering", "極光": "season_aurora", "狂歡": "season_carnival", "預言": "season_prophecy"}
        order = {"season_prophecy": 0, "season_performance": 1, "season_shattering": 2, "season_aurora": 3, "season_carnival": 4}
        profiles, unresolved = MIGRATE.season_profile("表演～狂歡無斷，缺破曉；預言季卡", aliases, order)
        by_id = {row["season_id"]: row for row in profiles}
        self.assertEqual(unresolved, [])
        self.assertEqual(by_id["season_shattering"]["status"], "confirmed_missing")
        self.assertEqual(by_id["season_aurora"]["status"], "owned_not_complete")
        self.assertEqual(by_id["season_prophecy"]["pass_owned"], "yes")
        summary = MIGRATE.season_summary(profiles, order)
        self.assertEqual(summary["earliest_season_id"], "season_prophecy")
        self.assertEqual(summary["gap_segments"][0]["season_ids"], ["season_shattering"])

    def test_plain_range_keeps_middle_seasons_unknown(self):
        aliases = {"表演": "season_performance", "狂歡": "season_carnival"}
        order = {"season_performance": 1, "season_middle_a": 2, "season_middle_b": 3, "season_carnival": 4}
        profiles, _ = MIGRATE.season_profile("表演～狂歡", aliases, order)
        by_id = {row["season_id"]: row for row in profiles}
        self.assertEqual(by_id["season_middle_a"]["status"], "unknown")
        self.assertEqual(by_id["season_middle_b"]["status"], "unknown")

    def test_feature_summary_is_parsed_with_field_level_provenance(self):
        aliases = {"表演": "season_performance"}
        order = {"season_performance": 1}
        listing, _ = MIGRATE.season_profile("未展開季節", aliases, order, "listing_text")
        summary, _ = MIGRATE.season_profile("表演季卡", aliases, order, "normalized_feature_summary")
        profiles = MIGRATE.merge_season_profiles(
            {"listing_text": listing, "normalized_feature_summary": summary}, order
        )
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["season_id"], "season_performance")
        self.assertEqual(profiles[0]["status"], "owned_not_complete")
        self.assertEqual(profiles[0]["pass_owned"], "yes")
        self.assertEqual(profiles[0]["evidence_state"], "text_claim")
        self.assertEqual(
            profiles[0]["evidence_sources"],
            ["pass_owned:normalized_feature_summary", "status:normalized_feature_summary"],
        )

    def test_conflicting_feature_summary_claims_fail_closed(self):
        aliases = {"表演": "season_performance"}
        order = {"season_performance": 1}
        listing, _ = MIGRATE.season_profile("表演畢業，表演季卡", aliases, order, "listing_text")
        summary, _ = MIGRATE.season_profile("表演半畢，表演無卡", aliases, order, "normalized_feature_summary")
        profile = MIGRATE.merge_season_profiles(
            {"listing_text": listing, "normalized_feature_summary": summary}, order
        )[0]
        self.assertEqual(profile["status"], "unknown")
        self.assertEqual(profile["pass_owned"], "unknown")
        self.assertEqual(profile["evidence_state"], "conflict")
        self.assertEqual(profile["review_status"], "needs_review")
        self.assertIn("status:listing_text", profile["evidence_sources"])
        self.assertIn("status:normalized_feature_summary", profile["evidence_sources"])

    def test_base_profile_combines_listing_and_normalized_summary(self):
        record = {
            "listing_id": "listing_0001", "listing_text": "表演畢業",
            "feature_summary": ["表演季卡"], "account_type_primary": "unknown",
            "wing_state": "unknown", "offer_kind": "seller_listing", "entity_kind": "single_account",
            "price_type": "unknown", "evidence_quality": "unknown", "bindings": [],
        }
        profile, unresolved = MIGRATE.base_profile(
            record, "account_0001", {"表演": "season_performance"},
            {"season_performance": 1}, {},
        )
        self.assertEqual(unresolved, [])
        season = profile["season_profiles"][0]
        self.assertEqual(season["status"], "complete")
        self.assertEqual(season["pass_owned"], "yes")
        self.assertEqual(
            season["evidence_sources"],
            ["pass_owned:normalized_feature_summary", "status:listing_text", "status:normalized_feature_summary"],
        )

    def test_feature_summary_only_claims_populate_structured_fields_with_provenance(self):
        record = {
            "listing_id": "listing_0001", "listing_text": "未完整列出帳號特徵",
            "feature_summary": ["白蠟 50、全圖畢業、二級斗、二手"],
            "account_type_primary": "unknown", "wing_state": "unknown",
            "offer_kind": "seller_listing", "entity_kind": "single_account", "price_type": "unknown",
            "evidence_quality": "unknown", "bindings": [],
        }
        profile, _ = MIGRATE.base_profile(record, "account_0001", {}, {}, {})
        self.assertEqual(profile["resources"]["values"]["white_candles"], 50)
        self.assertEqual(profile["map_completion"]["standard_maps"], "complete")
        self.assertEqual(profile["map_completion"]["second_tier_capes"], "partial")
        self.assertEqual(profile["ownership_history"], "second_owner")
        for field in ("resources.values.white_candles", "map_completion.standard_maps", "map_completion.second_tier_capes", "ownership_history"):
            self.assertEqual(profile["field_evidence"][field], {"sources": ["normalized_feature_summary"], "evidence_state": "text_claim"})

    def test_feature_summary_conflicts_fail_closed_by_field(self):
        record = {
            "listing_id": "listing_0001", "listing_text": "白蠟 10、全圖畢業、一手",
            "feature_summary": ["白蠟 20、幾乎全圖畢、二手"],
            "account_type_primary": "unknown", "wing_state": "unknown",
            "offer_kind": "seller_listing", "entity_kind": "single_account", "price_type": "unknown",
            "evidence_quality": "unknown", "bindings": [],
        }
        profile, _ = MIGRATE.base_profile(record, "account_0001", {}, {}, {})
        self.assertIsNone(profile["resources"]["values"]["white_candles"])
        self.assertEqual(profile["resources"]["evidence_state"], "conflict")
        self.assertEqual(profile["map_completion"]["standard_maps"], "unknown")
        self.assertEqual(profile["map_completion"]["evidence_state"], "conflict")
        self.assertEqual(profile["ownership_history"], "unknown")
        self.assertEqual(profile["review_status"], "needs_review")
        for field in ("resources.values.white_candles", "map_completion.standard_maps", "ownership_history"):
            self.assertEqual(profile["field_evidence"][field]["evidence_state"], "conflict")
            self.assertEqual(profile["field_evidence"][field]["sources"], ["listing_text", "normalized_feature_summary"])

    def test_approximate_resource_point_is_preserved_without_coercing_lower_bounds(self):
        parsed = MIGRATE.resource_vector("白蠟約 1831、愛心近130、紅蠟12；季蠟89")
        self.assertEqual(parsed["values"], {
            "white_candles": 1831, "hearts": 130,
            "red_candles": 12, "season_candles": 89,
        })
        self.assertEqual(parsed["claim_kinds"]["white_candles"], "approximate")
        self.assertEqual(parsed["claim_kinds"]["hearts"], "approximate")
        self.assertEqual(parsed["claim_kinds"]["red_candles"], "exact")
        lower_bound = MIGRATE.resource_vector("白蠟1000以上、愛心200+")
        self.assertIsNone(lower_bound["values"]["white_candles"])
        self.assertIsNone(lower_bound["values"]["hearts"])

    def test_inverted_exact_resource_claims_do_not_coerce_qualifiers_or_lower_bounds(self):
        parsed = MIGRATE.resource_vector("1831白蠟、130愛心、12紅蠟、89季蠟")
        self.assertEqual(parsed["values"], {
            "white_candles": 1831, "hearts": 130,
            "red_candles": 12, "season_candles": 89,
        })
        self.assertTrue(all(kind == "exact" for kind in parsed["claim_kinds"].values()))
        ambiguous = MIGRATE.resource_vector("約1831白蠟、2100+白蠟、1千白蠟")
        self.assertIsNone(ambiguous["values"]["white_candles"])

    def test_approximate_resource_provenance_survives_merge(self):
        listing = MIGRATE.resource_vector("白蠟約1831")
        summary = MIGRATE.resource_vector("")
        resources, evidence = MIGRATE.merge_resources(listing, summary)
        self.assertEqual(resources["values"]["white_candles"], 1831)
        self.assertEqual(evidence["resources.values.white_candles"]["claim_kind"], "approximate")

    def test_season_conflict_marks_profile_needs_review(self):
        record = {
            "listing_id": "listing_0001", "listing_text": "表演畢業",
            "feature_summary": ["表演半畢"], "account_type_primary": "unknown",
            "wing_state": "unknown", "offer_kind": "seller_listing", "entity_kind": "single_account",
            "price_type": "unknown", "evidence_quality": "unknown", "bindings": [],
        }
        profile, _ = MIGRATE.base_profile(
            record, "account_0001", {"表演": "season_performance"},
            {"season_performance": 1}, {},
        )
        self.assertEqual(profile["season_profiles"][0]["evidence_state"], "conflict")
        self.assertEqual(profile["review_status"], "needs_review")

    def test_ambiguous_winter_term_is_not_auto_mapped(self):
        aliases = {"凜冬": "season_should_not_be_used"}
        profiles, unresolved = MIGRATE.season_profile("凜冬畢業", aliases, {})
        self.assertEqual(profiles, [])
        self.assertEqual(unresolved, ["凜冬"])

    def test_collection_claims_require_exact_unambiguous_aliases_and_keep_provenance(self):
        aliases = {
            "正式斗篷": ("item", "item_formal_cape"),
            # An alias index is expected to have removed ambiguous spellings;
            # this unmatched near-spelling must never create an item ID.
        }
        listing = MIGRATE.collection_claims("含正式斗篷，不含近似斗篷", aliases, "listing_text")
        summary = MIGRATE.collection_claims("正式斗篷", aliases, "normalized_feature_summary")
        owned, set_rows, evidence = MIGRATE.merge_collection_claims(listing, summary)
        self.assertEqual(owned, {"item_formal_cape"})
        self.assertEqual(set_rows, [])
        self.assertEqual(evidence["collection.owned_item_ids"], {
            "sources": ["listing_text", "normalized_feature_summary"], "evidence_state": "text_claim",
        })

    def test_nested_short_alias_does_not_double_count_a_long_item_name(self):
        aliases = {
            "九色鹿角": ("item", "item_nine_colored_deer_antlers"),
            "鹿角": ("item", "item_days_feast_reindeer_antlers"),
        }
        owned, _ = MIGRATE.collection_claims("只有九色鹿角", aliases, "listing_text")
        self.assertEqual(owned, {"item_nine_colored_deer_antlers"})

    def test_buyer_requested_item_is_not_migrated_as_owned(self):
        record = {
            "listing_id": "listing_0015", "listing_text": "收號需求，希望有蝙蝠斗與九色鹿畢業禮",
            "feature_summary": ["希望有蝙蝠斗與九色鹿畢業禮"], "offer_kind": "buyer_budget", "entity_kind": "single_account",
            "account_type_primary": "unknown", "wing_state": "unknown", "price_type": "unknown",
            "evidence_quality": "unknown", "bindings": [],
        }
        profile, _ = MIGRATE.base_profile(
            record, "account_0015", {"九色鹿": "season_nine_colored_deer"}, {"season_nine_colored_deer": 1},
            {"season_nine_colored_deer": ["item_nine_colored_deer_ultimate"]},
            {"蝙蝠斗": ("item", "item_days_mischief_bat_cape")},
        )
        self.assertEqual(profile["collection"]["owned_item_ids"], [])
        self.assertEqual(profile["collection"]["graduation_reward_season_ids"], [])
        self.assertEqual(profile["season_profiles"], [])
        self.assertEqual(profile["base_account"]["account_type"], "unknown")
        self.assertEqual(profile["field_evidence"]["collection.owned_item_ids"]["evidence_state"], "unknown")

    def test_binding_claims_from_sources_conflict_fail_closed(self):
        bindings, evidence = MIGRATE.binding_matrix(
            {"bindings": [], "binding_details": {}}, "Google 可綁", "GG 死綁"
        )
        google = next(row for row in bindings["platforms"] if row["platform"] == "google")
        self.assertEqual(google["status"], "unknown")
        self.assertEqual(google["evidence_state"], "conflict")
        self.assertEqual(evidence["bindings.platforms.google"]["sources"], ["listing_text", "normalized_feature_summary"])

    def test_game_center_is_its_own_binding_platform(self):
        bindings, _ = MIGRATE.binding_matrix({"bindings": []}, "GC 不出，Apple 可綁，GG 可綁")
        by_platform = {row["platform"]: row for row in bindings["platforms"]}
        self.assertEqual(by_platform["game_center"]["status"], "high_risk")
        self.assertEqual(by_platform["apple"]["status"], "available")
        self.assertEqual(by_platform["google"]["status"], "available")
        tgc_bindings, _ = MIGRATE.binding_matrix({"bindings": []}, "TGC斗篷")
        tgc_by_platform = {row["platform"]: row for row in tgc_bindings["platforms"]}
        self.assertEqual(tgc_by_platform["game_center"]["status"], "unknown")

    def test_explicit_urgent_overrides_reduced_but_never_sold_claim(self):
        self.assertEqual(MIGRATE.normalize_market_price_type("reduced", "急售降價"), "urgent_sale")
        self.assertEqual(MIGRATE.normalize_market_price_type("sold_explicit", "急售後已售"), "sold_claim")
        self.assertEqual(MIGRATE.normalize_market_price_type("asking", "不急售，一般掛價"), "asking")
        self.assertEqual(MIGRATE.normalize_urgent_listing_price_type("buyout", "急售直購"), "urgent_sale")

    def test_unverified_two_character_alias_requires_context(self):
        index = MIGRATE.collection_aliases(ROOT)
        self.assertNotIn("紅斗", index)
        self.assertNotIn("鹿角", index)
        self.assertIn("任天堂紅斗", index)

    def test_explicit_ordinal_ownership_and_resident_map_completion_are_safe(self):
        self.assertEqual(MIGRATE.ownership_history("第一任私用"), "first_owner")
        self.assertEqual(MIGRATE.ownership_history("第2任"), "second_owner")
        self.assertEqual(MIGRATE.ownership_history("到買方第六任"), "multiple_owners")
        self.assertEqual(MIGRATE.map_completion("常駐圖畢業")["standard_maps"], "complete")

    def test_canonical_collection_enrichment_uses_only_owned_items_and_strict_event_availability(self):
        metadata = MIGRATE.canonical_collection_metadata(
            [
                {"item_id": "item_ultimate", "ultimate_reward": True, "season_id": "season_example", "collaboration": False, "set_ids": [], "source_type": "season", "availability_status": "temporarily_unavailable"},
                {"item_id": "item_collab_bundle", "ultimate_reward": False, "collaboration": True, "set_ids": ["set_bundle"], "source_type": "collaboration", "availability_status": "limited_time"},
                {"item_id": "item_recurring_event", "ultimate_reward": False, "collaboration": False, "set_ids": [], "source_type": "event", "availability_status": "recurring_event"},
                {"item_id": "item_limited_event", "ultimate_reward": False, "collaboration": False, "set_ids": [], "source_type": "event", "availability_status": "limited_time"},
            ],
            [{"set_id": "set_bundle", "set_type": "bundle"}],
        )
        values, evidence = MIGRATE.enrich_collection_from_canonical(
            {"item_ultimate", "item_collab_bundle", "item_recurring_event"},
            ["season_example"], metadata,
            {"sources": ["listing_text"], "evidence_state": "text_claim"},
        )
        self.assertEqual(values["graduation_rewards"], ["item_ultimate"])
        self.assertEqual(values["collaboration_items"], ["item_collab_bundle"])
        self.assertEqual(values["bundle_item_ids"], ["item_collab_bundle"])
        self.assertEqual(values["event_limited_item_ids"], [])
        self.assertEqual(evidence["collection.bundle_item_ids"], {"sources": ["listing_text"], "evidence_state": "text_claim"})
        unknown_values, unknown_evidence = MIGRATE.enrich_collection_from_canonical(
            {"item_collab_bundle"}, [], metadata, {"sources": [], "evidence_state": "conflict"},
        )
        self.assertEqual(unknown_values["collaboration_items"], [])
        self.assertEqual(unknown_evidence["collection.collaboration_items"]["evidence_state"], "conflict")

    def test_cjk_phrase_matching_does_not_depend_on_word_boundaries(self):
        self.assertTrue(MIGRATE.mentioned_without_negation("含TGC斗篷與白蠟", "TGC"))
        self.assertFalse(MIGRATE.mentioned_without_negation("不含TGC斗篷", "TGC"))

    def test_sold_claim_never_becomes_verified_sale(self):
        histories = [json.loads(line) for line in (ROOT / "data/curated/histories.jsonl").read_text(encoding="utf-8").splitlines() if line]
        claimed = [row for row in histories if row["sale_outcome"]["status"] == "sold_claimed"]
        self.assertGreater(len(claimed), 0)
        self.assertTrue(all(not row["sale_outcome"]["verified"] and row["sale_outcome"]["completed_sale_price_twd"] is None for row in claimed))

    def test_committed_derivatives_reflect_alias_binding_and_urgent_fixes(self):
        profiles = {
            row["account_id"]: row for row in (
                json.loads(line) for line in (ROOT / "data/normalized/account-profiles.jsonl").read_text(encoding="utf-8").splitlines() if line
            )
        }
        game_center = {row["platform"]: row["status"] for row in profiles["account_0040"]["bindings"]["platforms"]}
        self.assertEqual(game_center["game_center"], "unknown")
        self.assertNotIn("item_nintendo_red_cape", profiles["account_0141"]["collection"]["owned_item_ids"])
        for account_id in ("account_0197", "account_0282", "account_0314"):
            owned = profiles[account_id]["collection"]["owned_item_ids"]
            self.assertIn("item_nine_colored_deer_antlers", owned)
            self.assertNotIn("item_days_feast_reindeer_antlers", owned)
        histories = {
            row["history_id"]: row for row in (
                json.loads(line) for line in (ROOT / "data/curated/histories.jsonl").read_text(encoding="utf-8").splitlines() if line
            )
        }
        self.assertEqual(histories["history_0039"]["price_type"], "urgent_sale")
        self.assertEqual(histories["history_0066"]["price_type"], "urgent_sale")


if __name__ == "__main__":
    unittest.main()
