import json

from gainsay.overview import benchmark_result


def arms(*names):
    return [{"arm": n, "precision": 0.5, "recall": 0.5, "f1": 0.5} for n in names]


def five_types(role, size):
    return {
        "subset": {"size": size, "role": role},
        "scores": {"citation_level": {"arms": arms("gainsay", "no-tools")}, "all_types": {"arms": arms("gainsay")}},
    }


def test_the_full_split_is_preferred_over_the_held_out_subset(tmp_path):
    (tmp_path / "lephantomcite-heldout-n100-seed777.json").write_text(json.dumps(
        {"subset": {"size": 100}, "arms": arms("gainsay", "no-tools")}
    ))
    assert benchmark_result(tmp_path)["all_types"] is None
    (tmp_path / "lephantomcite-heldout-n100-seed777-five-types.json").write_text(json.dumps(five_types("heldout", 100)))
    assert benchmark_result(tmp_path)["role"] == "heldout"
    (tmp_path / "lephantomcite-full-n390-five-types.json").write_text(json.dumps(five_types("full", 390)))
    result = benchmark_result(tmp_path)
    assert (result["role"], result["size"]) == ("full", 390)
    assert set(result["all_types"]) == {"gainsay"}


def test_development_results_are_never_shown(tmp_path):
    (tmp_path / "lephantomcite-dev-n100-seed1-five-types.json").write_text(json.dumps(five_types("dev", 100)))
    assert benchmark_result(tmp_path) is None
