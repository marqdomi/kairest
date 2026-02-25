from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, SelectField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

class ProductoForm(FlaskForm):
    nombre = StringField('Nombre', validators=[DataRequired(), Length(max=100)])
    precio = DecimalField('Precio', validators=[DataRequired(), NumberRange(min=0)])
    categoria_id = SelectField(
        'Categoría',
        coerce=int,
        validators=[DataRequired()],
    )
    estacion_id = SelectField(
        'Estación',
        coerce=int,
        validators=[DataRequired()],
    )
    unidad = StringField('Unidad', validators=[Optional(), Length(max=30)])
    descripcion = StringField('Descripción', validators=[Optional(), Length(max=500)])
    submit = SubmitField('Guardar')