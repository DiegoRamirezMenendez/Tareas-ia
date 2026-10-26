 Ejercicio 1 — Cliff Walking


 Configuración y resultados:

Implementé Q-learning tabular en la cuadrícula de 4×12 con $\alpha = 0.5$, $\gamma = 1$, $\epsilon = 0.1$, 500 episodios (máximo 200 pasos por episodio) y la semilla 7. La tabla Q arranca en ceros y los empates se rompen en orden N, E, S, W.

Al correr `python cliff_walking.py`, el código valida los tres casos de prueba, entrena al agente, muestra la política y exporta los datos a `episode_returns.csv`. Con esta semilla, el agente obtuvo un promedio de −51.88 durante el entrenamiento y completó la ruta greedy de evaluación en 13 pasos con una recompensa de −13**.

Análisis:

 Ruta óptima: Sube un paso desde S, avanza 11 casillas al este por la fila superior y baja a G. Son 13 pasos con recompensa de −1 cada uno (total −13). Desviarse cuesta pasos extra y caer al acantilado castiga con −100.
Entrenamiento vs. Evaluación:  El retorno en entrenamiento es más bajo porque la exploración $\epsilon$-greedy hace que el agente caiga ocasionalmente. En la evaluación ($\epsilon = 0$), el agente sigue únicamente lo aprendido y hace el recorrido perfecto.
Mecánica del acantilado: Caer al acantilado otorga −100 y reinicia al agente en S, pero no termina el episodio. Por eso el target de Q-learning sigue considerando $\max_a Q(S, a)$. El episodio solo finaliza al llegar a G.