

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


ATOM_PATTERN = re.compile(r"^([A-Za-z_]\w*)\s*(?:\((.*)\))?$")
BASE_PATH = Path(__file__).with_name("biblioteca.json")


@dataclass(frozen=True)
class Atom:
    predicate: str
    arguments: tuple[str, ...] = ()

    def __str__(self) -> str:
        if not self.arguments:
            return self.predicate
        return f"{self.predicate}({', '.join(self.arguments)})"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    premises: tuple[Atom, ...]
    conclusion: Atom


@dataclass
class KnowledgeBase:
    facts: list[Atom]
    rules: list[Rule]
    queries: list[Atom]


@dataclass
class Result:
    proved: bool
    inferred: list[Atom]
    trace: list[str]


def parse_atom(text: str) -> Atom:
    match = ATOM_PATTERN.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"Átomo no válido: {text!r}")
    raw_arguments = match.group(2)
    if raw_arguments is None or not raw_arguments.strip():
        return Atom(match.group(1))
    arguments = tuple(argument.strip() for argument in raw_arguments.split(","))
    if any(not argument for argument in arguments):
        raise ValueError(f"Argumento vacío en el átomo: {text!r}")
    return Atom(match.group(1), arguments)


def load_knowledge_base(path: Path = BASE_PATH) -> KnowledgeBase:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    facts = [parse_atom(fact) for fact in data["facts"]]
    rules = [
        Rule(
            rule["id"],
            tuple(parse_atom(premise) for premise in rule["if"]),
            parse_atom(rule["then"]),
        )
        for rule in data["rules"]
    ]
    queries = [parse_atom(query) for query in data["queries"]]
    return KnowledgeBase(facts, rules, queries)


def is_variable(term: str) -> bool:
    return bool(term) and term[0].islower()


def apply_term(term: str, substitution: dict[str, str]) -> str:
    visited: set[str] = set()
    while is_variable(term) and term in substitution and term not in visited:
        visited.add(term)
        term = substitution[term]
    return term


def apply_atom(atom: Atom, substitution: dict[str, str]) -> Atom:
    return Atom(
        atom.predicate,
        tuple(apply_term(argument, substitution) for argument in atom.arguments),
    )


def unify_terms(
    left: str, right: str, substitution: dict[str, str]
) -> dict[str, str] | None:
    left = apply_term(left, substitution)
    right = apply_term(right, substitution)
    if left == right:
        return substitution
    if is_variable(left):
        substitution[left] = right
        return substitution
    if is_variable(right):
        substitution[right] = left
        return substitution
    return None


def unify(
    left: Atom, right: Atom, substitution: dict[str, str] | None = None
) -> dict[str, str] | None:
    if left.predicate != right.predicate or len(left.arguments) != len(right.arguments):
        return None
    result = dict(substitution or {})
    for left_term, right_term in zip(left.arguments, right.arguments):
        result = unify_terms(left_term, right_term, result)
        if result is None:
            return None
    return result


def standardize(rule: Rule, counter: int) -> Rule:
    names: dict[str, str] = {}

    def rename(atom: Atom) -> Atom:
        arguments = []
        for argument in atom.arguments:
            if is_variable(argument):
                names.setdefault(argument, f"{argument}_{counter}")
                arguments.append(names[argument])
            else:
                arguments.append(argument)
        return Atom(atom.predicate, tuple(arguments))

    return Rule(
        rule.rule_id,
        tuple(rename(premise) for premise in rule.premises),
        rename(rule.conclusion),
    )


def satisfy(
    premises: tuple[Atom, ...],
    facts: list[Atom],
    substitution: dict[str, str],
) -> list[dict[str, str]]:
    if not premises:
        return [substitution]
    goal = apply_atom(premises[0], substitution)
    solutions = []
    for fact in facts:
        updated = unify(goal, fact, substitution)
        if updated is not None:
            solutions.extend(satisfy(premises[1:], facts, updated))
    return solutions


def format_substitution(substitution: dict[str, str]) -> str:
    values = ", ".join(
        f"{name}/{apply_term(value, substitution)}"
        for name, value in sorted(substitution.items())
    )
    return "{" + values + "}" if values else "{}"


def forward_chain(kb: KnowledgeBase, query: Atom) -> Result:
    facts = list(kb.facts)
    inferred: list[Atom] = []
    trace = [f"Hechos iniciales: {', '.join(map(str, facts))}"]
    counter = 0
    round_number = 1

    while True:
        trace.append(f"Ronda {round_number}")
        facts_at_start = list(facts)
        new_facts: list[Atom] = []
        for rule in kb.rules:
            counter += 1
            fresh_rule = standardize(rule, counter)
            for substitution in satisfy(fresh_rule.premises, facts_at_start, {}):
                conclusion = apply_atom(fresh_rule.conclusion, substitution)
                if conclusion in facts or conclusion in new_facts:
                    continue
                new_facts.append(conclusion)
                inferred.append(conclusion)
                trace.append(
                    f"  Dispara {rule.rule_id} "
                    f"{format_substitution(substitution)} -> {conclusion}"
                )
        if not new_facts:
            trace.append("  Sin hechos nuevos; termina.")
            break
        facts.extend(new_facts)
        round_number += 1

    proved = any(unify(query, fact) is not None for fact in facts)
    trace.append(f"Consulta {query}: {'PROBADA' if proved else 'NO PROBADA'}")
    return Result(proved, inferred, trace)


def backward_chain(kb: KnowledgeBase, query: Atom) -> Result:
    trace = [f"Consulta: {query}"]
    visited_goals: list[Atom] = []
    counter = 0

    def prove(
        goal: Atom,
        substitution: dict[str, str],
        stack: tuple[str, ...],
        depth: int,
    ) -> dict[str, str] | None:
        nonlocal counter
        goal = apply_atom(goal, substitution)
        indent = "  " * depth
        key = str(goal)
        if key in stack:
            trace.append(f"{indent}Ciclo: {goal}; se corta este camino.")
            return None
        visited_goals.append(goal)
        trace.append(f"{indent}Meta: {goal}")

        for fact in kb.facts:
            updated = unify(goal, fact, substitution)
            if updated is not None:
                trace.append(f"{indent}  Hecho: {fact}")
                return updated

        for rule in kb.rules:
            counter += 1
            fresh_rule = standardize(rule, counter)
            updated = unify(goal, fresh_rule.conclusion, substitution)
            if updated is None:
                continue
            trace.append(
                f"{indent}  Prueba {rule.rule_id} "
                f"{format_substitution(updated)}"
            )
            current = updated
            for premise in fresh_rule.premises:
                current = prove(premise, current, stack + (key,), depth + 1)
                if current is None:
                    break
            if current is not None:
                return current
            trace.append(f"{indent}  Falla {rule.rule_id}; intenta otra regla.")

        trace.append(f"{indent}Falla la meta: {goal}")
        return None

    answer = prove(query, {}, (), 0)
    trace.append(f"Consulta {query}: {'PROBADA' if answer is not None else 'NO PROBADA'}")
    unique_goals = list(dict.fromkeys(visited_goals))
    return Result(answer is not None, unique_goals, trace)


def show_result(algorithm: str, query: Atom, result: Result) -> None:
    print(f"\n{algorithm} -- {query}")
    print("-" * 60)
    print("\n".join(result.trace))
    if algorithm.startswith("Adelante"):
        print("Atomos nuevos:", ", ".join(map(str, result.inferred)) or "(ninguno)")
    else:
        print("Metas visitadas:", ", ".join(map(str, result.inferred)) or "(ninguna)")


def main() -> None:
    kb = load_knowledge_base()
    for query in kb.queries:
        show_result("Adelante", query, forward_chain(kb, query))
        show_result("Atrás", query, backward_chain(kb, query))

    kb_with_luis_credential = KnowledgeBase(
        kb.facts + [parse_atom("TieneCredencial(Luis)")], kb.rules, kb.queries
    )
    luis_query = parse_atom("AccesoNoche(Luis)")
    original_luis_result = forward_chain(kb, luis_query)
    updated_luis_result = forward_chain(kb_with_luis_credential, luis_query)
    show_result("Adelante (con credencial de Luis)", luis_query, updated_luis_result)
    additional_atoms = [
        atom for atom in updated_luis_result.inferred if atom not in original_luis_result.inferred
    ]
    print("Atomos adicionales vs. base original:", ", ".join(map(str, additional_atoms)))
    show_result(
        "Atrás (con credencial de Luis)",
        luis_query,
        backward_chain(kb_with_luis_credential, luis_query),
    )


if __name__ == "__main__":
    main()
