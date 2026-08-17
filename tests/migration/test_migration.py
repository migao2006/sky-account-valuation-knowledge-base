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
COMPARABLES_SPEC = importlib.util.spec_from_file_location("build_comparables", ROOT / "tools/normalize/build_comparables.py")
COMPARABLES = importlib.util.module_from_spec(COMPARABLES_SPEC)
COMPARABLES_SPEC.loader.exec_module(COMPARABLES)


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

    def test_explicit_sale_exchange_offer_fails_closed_before_strict_market_selection(self):
        record = {
            "listing_text": "售／換：夢想斷季帳；出價 5700 台幣。",
            "offer_kind": "seller_listing", "entity_kind": "single_account",
            "core_candidate": True, "exclusion_reason": "",
        }
        MIGRATE.apply_explicit_trade_semantics(record)
        self.assertEqual(record["offer_kind"], "mixed")
        self.assertEqual(record["entity_kind"], "unknown")
        self.assertFalse(record["core_candidate"])
        self.assertEqual(record["exclusion_reason"], "explicit_cash_and_exchange_offer_requires_review")

    def test_badge_and_installment_price_alternatives_are_reviewed_not_collapsed(self):
        text = "即付不含勳章7.0萬、含勳章7.2萬，分期7.3至7.5萬；台幣匯款。"
        review = MIGRATE.price_semantic_review(text, "asking")
        self.assertEqual(review, {
            "urgency": "unknown", "multi_price": True,
            "evidence_state": "text_claim", "review_status": "needs_review",
            "reason_codes": ["multiple_price_terms", "badge_inclusion_price_variants", "installment_price_variants"],
        })
        self.assertIsNone(MIGRATE.price_semantic_review("含勳章 70000 台幣", "asking"))

    def test_installment_surcharge_is_a_multi_price_review_without_calculation(self):
        text = "標價 56000 台幣；最多分三期，超過一期加 500；出售前持續養號。"
        review = MIGRATE.price_semantic_review(text, "asking")
        self.assertEqual(review, {
            "urgency": "unknown", "multi_price": True,
            "evidence_state": "text_claim", "review_status": "needs_review",
            "reason_codes": ["multiple_price_terms", "installment_price_variants"],
        })
        # Payment timing alone is not an alternative account price.
        self.assertIsNone(MIGRATE.price_semantic_review("標價 56000 台幣，可分三期付款。", "asking"))

    def test_comparables_rebuild_preserves_listing_0388_installment_gate(self):
        listings = {row["listing_id"]: row for row in MIGRATE.read_jsonl(ROOT / "data/normalized/listings.jsonl")}
        histories = {row["history_id"]: row for row in MIGRATE.read_jsonl(ROOT / "data/curated/histories.jsonl")}
        review = COMPARABLES.price_semantic_review(listings["listing_0388"], histories["history_0068"])
        self.assertIsNotNone(review)
        self.assertTrue(review["multi_price"])
        self.assertEqual(review["review_status"], "needs_review")
        self.assertEqual(review["reason_codes"], ["multiple_price_terms", "installment_price_variants"])

    def test_formal_mixed_exchange_and_multi_price_regressions_fail_closed(self):
        listings = {row["listing_id"]: row for row in MIGRATE.read_jsonl(ROOT / "data/normalized/listings.jsonl")}
        histories = {row["history_id"]: row for row in MIGRATE.read_jsonl(ROOT / "data/curated/histories.jsonl")}
        mixed = listings["listing_0808"]
        self.assertEqual((mixed["offer_kind"], mixed["entity_kind"]), ("mixed", "unknown"))
        self.assertFalse(mixed["core_candidate"])
        self.assertIn("explicit_cash_and_exchange_offer_requires_review", mixed["exclusion_reason"])
        multi_price = histories["history_0062"]
        self.assertEqual(multi_price["selected_price_twd"], 70000)  # historical observation is preserved, not replaced
        self.assertTrue(multi_price["price_semantic_review"]["multi_price"])
        self.assertEqual(multi_price["price_semantic_review"]["review_status"], "needs_review")

    def test_verified_date_does_not_infer_server_evidence(self):
        histories = {row["history_id"]: row for row in MIGRATE.read_jsonl(ROOT / "data/curated/histories.jsonl")}
        dated = histories["history_0066"]
        self.assertTrue(dated["date_verified"])
        self.assertEqual(dated["server"], "unknown")
        self.assertFalse(dated["server_verified"])

    def test_mixed_exchange_listing_is_removed_from_near_miss_queue_without_fabricated_approval(self):
        queue = MIGRATE.read_jsonl(ROOT / "data/review/market-near-miss-field-review.jsonl")
        approvals = MIGRATE.read_jsonl(ROOT / "data/review/market-near-miss-approved-evidence.jsonl")
        self.assertEqual(len(queue), 16)
        self.assertNotIn("listing_0808", {row["listing_id"] for row in queue})
        self.assertEqual(approvals, [])

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

    def test_context_gated_assembly_and_shattering_aliases_cover_formal_listings_only(self):
        aliases = MIGRATE.catalog_aliases(ROOT)
        order = {row["season_id"]: int(row["order_index"]) for row in MIGRATE.read_jsonl(ROOT / "knowledge/seasons/seasons.jsonl")}
        source = {row["listing_id"]: row for row in MIGRATE.read_jsonl(ROOT / "data/source/listings.jsonl")}

        expected = {
            "listing_0177": "season_assembly",  # 畢業季節：集結
            "listing_0307": "season_assembly",  # 季节清单中的集结季
            "listing_0600": "season_shattering",  # 破碎季無翼
        }
        for listing_id, season_id in expected.items():
            with self.subTest(listing_id=listing_id):
                profiles, unresolved = MIGRATE.season_profile(source[listing_id]["listing_text"], aliases, order)
                self.assertIn(season_id, {row["season_id"] for row in profiles})
                self.assertEqual(unresolved, [])

        for listing_id in ("listing_0061", "listing_0166"):
            with self.subTest(negative_listing_id=listing_id):
                profiles, _ = MIGRATE.season_profile(source[listing_id]["listing_text"], aliases, order)
                self.assertNotIn("season_shattering", {row["season_id"] for row in profiles})

    def test_context_gated_season_aliases_do_not_turn_negation_or_unknown_into_ownership(self):
        aliases = {"集結": "season_assembly", "集结": "season_assembly", "破碎": "season_shattering"}
        profiles, unresolved = MIGRATE.season_profile("不含破碎、試煉；集結材料已收齊", aliases, {})
        self.assertEqual(profiles, [])
        self.assertEqual(unresolved, [])
        self.assertEqual(MIGRATE.season_terms("不含破碎、試煉；集結材料已收齊"), [])

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
            [
                "pass_owned:normalized_feature_summary",
                "status:listing_text",
                "status:normalized_feature_summary",
                "status_completion_positive:listing_text",
            ],
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

    def test_game_center_cannot_transfer_is_high_risk(self):
        bindings, evidence = MIGRATE.binding_matrix(
            {"bindings": []}, "GC 因忘記帳號無法轉出", ""
        )
        game_center = next(row for row in bindings["platforms"] if row["platform"] == "game_center")
        self.assertEqual(game_center["status"], "high_risk")
        self.assertEqual(game_center["evidence_state"], "text_claim")
        self.assertEqual(evidence["bindings.platforms.game_center"]["sources"], ["listing_text"])

    def test_ideographic_comma_keeps_binding_claims_separate(self):
        bindings, _ = MIGRATE.binding_matrix({}, "Google 不出、Apple 可綁", "")
        by_platform = {row["platform"]: row for row in bindings["platforms"]}
        self.assertEqual(by_platform["google"]["status"], "high_risk")
        self.assertEqual(by_platform["apple"]["status"], "available")
        contradictory, _ = MIGRATE.binding_matrix({}, "Google 可綁但前任綁定不出", "")
        google = next(row for row in contradictory["platforms"] if row["platform"] == "google")
        self.assertEqual(google["status"], "high_risk")
        revoked, _ = MIGRATE.binding_matrix({}, "GG 註銷、GC ID 遺失、其他可換綁", "")
        revoked_by_platform = {row["platform"]: row for row in revoked["platforms"]}
        self.assertEqual(revoked_by_platform["google"]["status"], "high_risk")
        self.assertEqual(revoked_by_platform["game_center"]["status"], "high_risk")

    def test_half_complete_phrase_is_partial_not_complete(self):
        profiles, unresolved = MIGRATE.season_profile(
            "破碎半畢業", {"破碎": "season_shattering"}, {"season_shattering": 1}
        )
        self.assertEqual(unresolved, [])
        self.assertEqual(profiles[0]["status"], "partial")
        self.assertNotIn("status_completion_positive:listing_text", profiles[0]["evidence_sources"])

    def test_shared_ideographic_comma_binding_suffix_applies_only_to_platform_list(self):
        bindings, _ = MIGRATE.binding_matrix({}, "GG、GC、NS 前號主不出", "")
        by_platform = {row["platform"]: row["status"] for row in bindings["platforms"]}
        self.assertEqual(by_platform["google"], "high_risk")
        self.assertEqual(by_platform["game_center"], "high_risk")
        self.assertEqual(by_platform["nintendo"], "high_risk")
        unbound, _ = MIGRATE.binding_matrix({}, "Nintendo 可解綁", "")
        nintendo = next(row for row in unbound["platforms"] if row["platform"] == "nintendo")
        self.assertEqual(nintendo["status"], "available")

    def test_multi_match_binding_segments_merge_with_risk_priority(self):
        bindings, _ = MIGRATE.binding_matrix(
            {}, "Google、Apple ID、任天堂綁定不出，Google、PlayStation、Steam 可出", ""
        )
        by_platform = {row["platform"]: row["status"] for row in bindings["platforms"]}
        self.assertEqual(by_platform["google"], "high_risk")
        self.assertEqual(by_platform["apple"], "high_risk")
        self.assertEqual(by_platform["nintendo"], "high_risk")
        self.assertEqual(by_platform["playstation"], "available")
        self.assertEqual(by_platform["steam"], "available")

    def test_sale_verbs_are_not_inferred_as_binding_availability(self):
        listings = {row["listing_id"]: row for row in MIGRATE.read_jsonl(ROOT / "data/normalized/listings.jsonl")}
        for listing_id, platforms in {
            "listing_0214": ("google", "apple"),
            "listing_0960": ("apple",),
        }.items():
            row = listings[listing_id]
            bindings, _ = MIGRATE.binding_matrix(row, row["listing_text"], "\n".join(row.get("feature_summary", [])))
            by_platform = {entry["platform"]: entry["status"] for entry in bindings["platforms"]}
            for platform in platforms:
                with self.subTest(listing_id=listing_id, platform=platform):
                    self.assertNotEqual(by_platform[platform], "available")

    def test_partial_claims_do_not_cross_season_list_delimiters(self):
        aliases = {
            "表演": "season_performance", "破曉": "season_shattering",
            "二重奏": "season_duets", "青鳥": "season_blue_bird",
        }
        order = {season_id: index for index, season_id in enumerate(aliases.values())}
        profiles, _ = MIGRATE.season_profile("表演、破曉 1/2、二重奏 2/3、青鳥", aliases, order)
        by_season = {row["season_id"]: row["status"] for row in profiles}
        self.assertEqual(by_season["season_performance"], "owned_not_complete")
        self.assertEqual(by_season["season_shattering"], "partial")
        self.assertEqual(by_season["season_duets"], "partial")
        self.assertEqual(by_season["season_blue_bird"], "owned_not_complete")

    def test_committed_half_complete_and_binding_risk_regressions(self):
        profiles = {
            row["account_id"]: row
            for row in MIGRATE.read_jsonl(ROOT / "data/normalized/account-profiles.jsonl")
        }
        half_complete = {
            "account_0048": ("season_carnival",),
            "account_0123": ("season_two_embers_part_1",),
            "account_0246": ("season_prophecy",),
            "account_0375": ("season_passage", "season_moments"),
        }
        for account_id, season_ids in half_complete.items():
            by_season = {row["season_id"]: row["status"] for row in profiles[account_id]["season_profiles"]}
            for season_id in season_ids:
                self.assertEqual(by_season[season_id], "partial", (account_id, season_id))

        expected_bindings = {
            "account_0203": {"google": "available", "game_center": "available", "facebook": "available"},
            "account_0291": {"google": "high_risk", "game_center": "high_risk"},
            "account_0301": {"google": "high_risk", "game_center": "high_risk"},
            "account_0388": {"game_center": "high_risk"},
            "account_0391": {"google": "high_risk", "apple": "high_risk", "nintendo": "high_risk", "playstation": "available", "steam": "available"},
            "account_0435": {"google": "high_risk"},
            "account_0484": {"google": "high_risk", "facebook": "available"},
            "account_0665": {"google": "high_risk", "facebook": "available"},
            "account_0677": {"google": "available", "nintendo": "high_risk"},
            "account_0675": {"google": "high_risk"},
            "account_0756": {"google": "high_risk"},
            "account_0757": {"google": "high_risk", "huawei": "available"},
            "account_0784": {"apple": "high_risk", "facebook": "high_risk"},
            "account_0930": {"google": "high_risk", "facebook": "available"},
            "account_0932": {"google": "available", "game_center": "high_risk", "nintendo": "high_risk"},
            "account_1019": {"google": "high_risk", "huawei": "available"},
        }
        for account_id, expected in expected_bindings.items():
            by_platform = {
                row["platform"]: row["status"]
                for row in profiles[account_id]["bindings"]["platforms"]
            }
            for platform, status in expected.items():
                self.assertEqual(by_platform[platform], status, (account_id, platform))

    def test_committed_non_single_account_binding_segment_regressions(self):
        listings = {row["listing_id"]: row for row in MIGRATE.read_jsonl(ROOT / "data/normalized/listings.jsonl")}
        expected = {
            "listing_0042": {"facebook": "high_risk", "google": "high_risk", "nintendo": "high_risk", "apple": "available", "steam": "available"},
            "listing_0056": {"nintendo": "available"},
        }
        for listing_id, statuses in expected.items():
            row = listings[listing_id]
            bindings, _ = MIGRATE.binding_matrix(row, row["listing_text"], "\n".join(row.get("feature_summary", [])))
            by_platform = {entry["platform"]: entry["status"] for entry in bindings["platforms"]}
            for platform, status in statuses.items():
                self.assertEqual(by_platform[platform], status, (listing_id, platform))

    def test_committed_season_partial_scope_regressions(self):
        profiles = {
            row["account_id"]: row
            for row in MIGRATE.read_jsonl(ROOT / "data/normalized/account-profiles.jsonl")
        }
        expected = {
            "account_0165": {
                "season_performance": "complete", "season_shattering": "partial",
                "season_duets": "partial", "season_blue_bird": "complete",
            },
            "account_0052": {
                "season_aurora": "complete", "season_remembrance": "complete",
                "season_passage": "complete", "season_moments": "complete",
                "season_revival": "complete", "season_carnival": "owned_not_complete",
            },
        }
        for account_id, expected_statuses in expected.items():
            by_season = {row["season_id"]: row["status"] for row in profiles[account_id]["season_profiles"]}
            for season_id, status in expected_statuses.items():
                self.assertEqual(by_season[season_id], status, (account_id, season_id))

    def test_partial_ratio_does_not_cross_whitespace_season_boundaries(self):
        aliases = {
            "魔法": "season_enchantment", "小王子": "season_little_prince",
            "姆明": "season_moomin", "夜行": "season_passage",
        }
        order = {season_id: index for index, season_id in enumerate(aliases.values())}
        profiles, _ = MIGRATE.season_profile("魔法1/2 小王子；姆明1/3 夜行", aliases, order)
        statuses = {row["season_id"]: row["status"] for row in profiles}
        self.assertEqual(statuses["season_enchantment"], "partial")
        self.assertEqual(statuses["season_moomin"], "partial")
        self.assertEqual(statuses["season_little_prince"], "owned_not_complete")
        self.assertEqual(statuses["season_passage"], "owned_not_complete")

        formal = {
            row["account_id"]: row
            for row in MIGRATE.read_jsonl(ROOT / "data/normalized/account-profiles.jsonl")
        }
        account_0189 = {row["season_id"]: row["status"] for row in formal["account_0189"]["season_profiles"]}
        account_0291 = {row["season_id"]: row["status"] for row in formal["account_0291"]["season_profiles"]}
        self.assertNotEqual(account_0189.get("season_little_prince"), "partial")
        self.assertNotEqual(account_0189.get("season_passage"), "partial")
        self.assertNotEqual(account_0291.get("season_performance"), "partial")
        self.assertNotEqual(account_0291.get("season_two_embers_part_1"), "partial")

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

    def test_platform_first_binding_is_not_account_first_owner(self):
        source = {row["listing_id"]: row for row in MIGRATE.read_jsonl(ROOT / "data/source/listings.jsonl")}
        self.assertEqual(MIGRATE.ownership_history("Google 與 Apple 為第一任持有"), "unknown")
        for listing_id in ("listing_0239", "listing_0467", "listing_0544", "listing_0669"):
            with self.subTest(listing_id=listing_id):
                self.assertEqual(MIGRATE.ownership_history(source[listing_id]["listing_text"]), "multiple_owners")
                if listing_id in {"listing_0544", "listing_0669"}:
                    self.assertEqual(MIGRATE.ownership_history(source[listing_id]["account_features"]), "multiple_owners")

    def test_directly_negated_season_completion_never_becomes_complete(self):
        aliases = MIGRATE.catalog_aliases(ROOT)
        order = {row["season_id"]: int(row["order_index"]) for row in MIGRATE.read_jsonl(ROOT / "knowledge/seasons/seasons.jsonl")}
        source = {row["listing_id"]: row for row in MIGRATE.read_jsonl(ROOT / "data/source/listings.jsonl")}
        expected = {
            "listing_0057": ("season_blue_bird", "season_lightmending", "season_dear_van_gogh"),
            "listing_0298": ("season_carnival",),
            "listing_0314": ("season_prophecy",),
            "listing_0380": ("season_radiance",),
            "listing_0414": ("season_carnival",),
            "listing_0664": ("season_shattering", "season_nesting"),
            "listing_0719": ("season_dear_van_gogh",),
            "listing_0950": ("season_nine_colored_deer",),
        }
        for listing_id, season_ids in expected.items():
            profiles, _ = MIGRATE.season_profile(source[listing_id]["listing_text"], aliases, order)
            by_id = {row["season_id"]: row for row in profiles}
            for season_id in season_ids:
                with self.subTest(listing_id=listing_id, season_id=season_id):
                    self.assertIn(season_id, by_id)
                    self.assertEqual(by_id[season_id]["status"], "owned_not_complete")

    def test_same_source_completion_contradiction_fails_closed(self):
        profiles, _ = MIGRATE.season_profile("表演畢業；表演未畢業", {"表演": "season_performance"}, {})
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["status"], "unknown")
        self.assertEqual(profiles[0]["evidence_state"], "conflict")
        self.assertIn("status_completion_positive:listing_text", profiles[0]["evidence_sources"])
        self.assertIn("status_completion_negative:listing_text", profiles[0]["evidence_sources"])

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

    def test_legacy_market_records_are_research_only_and_propagated_to_comparables(self):
        histories = {row["history_id"]: row for row in MIGRATE.read_jsonl(ROOT / "data/curated/histories.jsonl")}
        accounts = {row["history_id"]: row for row in MIGRATE.read_jsonl(ROOT / "data/comparables/accounts.jsonl")}
        self.assertTrue(all(row["market_data_authorization"]["status"] == "legacy_research_only" for row in histories.values()))
        self.assertTrue(all(row["market_data_authorization"]["allowed_uses"] == ["research"] for row in histories.values()))
        self.assertEqual({key: row["market_data_authorization"] for key, row in accounts.items()}, {key: row["market_data_authorization"] for key, row in histories.items()})

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
