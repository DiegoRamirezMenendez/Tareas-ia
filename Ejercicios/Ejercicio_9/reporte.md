# Reporte

Para resolver el ejercicio preparé la base de conocimiento en
`biblioteca.json` y el programa `solucion.py`. Al ejecutar el programa se
pueden ver las trazas de los dos métodos. 

## Resultados

| Consulta | Hacia adelante | Hacia atrás |
|---|---|---|
| `AccesoNoche(Ana)` | Sí | Sí |
| `AccesoNoche(Luis)` | No | No |
| `AccesoNoche(Marta)` | Sí | Sí |

Con el encadenamiento hacia adelante se obtienen, en este orden,
`Miembro(Ana)`, `Miembro(Marta)`, `Becario(Ana)`, `AccesoNoche(Ana)` y
`AccesoNoche(Marta)`. Primero se derivan los miembros y la beca; después,
con esos resultados disponibles, se derivan los accesos. Luis no tiene
credencial ni es profesor, así que no llega a ser miembro y no puede entrar
de noche.

## ¿Por qué los métodos dan trazas diferentes?

`Becario(Ana)` aparece con el encadenamiento hacia adelante porque este
método revisa todas las reglas que puede aplicar a los hechos, aunque una
regla no sea necesaria para contestar la pregunta. En cambio, al buscar
`AccesoNoche(Ana)` hacia atrás, solo se siguen las reglas que ayudan a
demostrar ese acceso: `R_acceso` y `R_miembro_est`. Como ser becario no es
necesario para probarlo, `R_beca` no se usa.

Para demostrar que Marta es miembro, el programa intenta primero
`R_miembro_est`, porque aparece antes en la lista de reglas. Esa opción falla:
no tenemos el hecho `Estudiante(Marta)`. Luego intenta `R_miembro_prof`, que sí
funciona porque `Profesor(Marta)` está en la base.

## ¿Qué pasa si Luis consigue una credencial?

Al agregar el hecho `TieneCredencial(Luis)`, el programa deriva para Luis
`Miembro(Luis)`, `Becario(Luis)` y `AccesoNoche(Luis)`. Por lo tanto, la
consulta de su acceso queda probada con los dos métodos. Hacia atrás, la
prueba usa `R_acceso` para demostrar el acceso y `R_miembro_est` para
demostrar que Luis es miembro.
