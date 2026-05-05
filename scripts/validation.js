const form = document.querySelector('#application-form');

if (form) {
	const statusBox = document.querySelector('#form-status');
	const lowVolumeWarning = document.querySelector('#low-volume-warning');
	const fields = {
		companyName: form.querySelector('#companyName'),
		contactPerson: form.querySelector('#contactPerson'),
		corporateEmail: form.querySelector('#corporateEmail'),
		phone: form.querySelector('#phone'),
		website: form.querySelector('#website'),
		countryOperation: form.querySelector('#countryOperation'),
		productType: form.querySelector('#productType'),
		monthlyVolume: form.querySelector('#monthlyVolume'),
		comments: form.querySelector('#comments'),
		privacyPolicy: form.querySelector('#privacyPolicy'),
	};

	const servicesCheckboxes = Array.from(form.querySelectorAll('input[name="services"]'));
	const other3plRadios = Array.from(form.querySelectorAll('input[name="other3pl"]'));
	const commentsCounter = document.querySelector('#comments-counter');
	let skipResetStatusClear = false;

	const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
	const urlRegex = /^https?:\/\/.+/i;
	const phoneRegex = /^\+[0-9]{1,3}\s.+/;

	const applyErrorStyles = (element) => {
		element.classList.remove('border-slate-600', 'focus:border-cyan-400', 'focus:ring-cyan-500/40');
		element.classList.add('border-red-500', 'focus:border-red-400', 'focus:ring-red-500/30');
		element.setAttribute('aria-invalid', 'true');
	};

	const clearErrorStyles = (element) => {
		element.classList.remove('border-red-500', 'focus:border-red-400', 'focus:ring-red-500/30');
		element.classList.add('border-slate-600', 'focus:border-cyan-400', 'focus:ring-cyan-500/40');
		element.setAttribute('aria-invalid', 'false');
	};

	const setError = (element, errorId, message) => {
		const errorNode = document.querySelector(`#${errorId}`);
		if (errorNode) {
			errorNode.textContent = message;
		}
		if (element) {
			applyErrorStyles(element);
		}
	};

	const clearError = (element, errorId) => {
		const errorNode = document.querySelector(`#${errorId}`);
		if (errorNode) {
			errorNode.textContent = '';
		}
		if (element) {
			clearErrorStyles(element);
		}
	};

	const setGroupError = (elements, errorId, message) => {
		const errorNode = document.querySelector(`#${errorId}`);
		if (errorNode) {
			errorNode.textContent = message;
		}
		elements.forEach((item) => item.setAttribute('aria-invalid', 'true'));
	};

	const clearGroupError = (elements, errorId) => {
		const errorNode = document.querySelector(`#${errorId}`);
		if (errorNode) {
			errorNode.textContent = '';
		}
		elements.forEach((item) => item.setAttribute('aria-invalid', 'false'));
	};

	const hideStatusMessages = () => {
		if (statusBox) {
			statusBox.classList.add('hidden');
			statusBox.textContent = '';
		}
	};

	const updateLowVolumeWarning = () => {
		const isLowVolume = fields.monthlyVolume.value === '0-100';
		const hasProductType = fields.productType.value !== '';
		if (lowVolumeWarning) {
			if (isLowVolume && hasProductType) {
				lowVolumeWarning.classList.remove('hidden');
				lowVolumeWarning.textContent =
					'Para volúmenes menores a 100 envíos mensuales, nuestros servicios podrían no ser la solución más eficiente. ¿Seguro que quieres continuar?';
			} else {
				lowVolumeWarning.classList.add('hidden');
				lowVolumeWarning.textContent = '';
			}
		}
	};

	const updateCommentsCounter = () => {
		const length = fields.comments.value.length;
		if (commentsCounter) {
			commentsCounter.textContent = `${length}/500`;
		}
	};

	const validateCompanyName = () => {
		const value = fields.companyName.value.trim();
		if (value.length < 2) {
			setError(fields.companyName, 'companyName-error', 'El nombre de la empresa debe tener al menos 2 caracteres');
			return false;
		}
		clearError(fields.companyName, 'companyName-error');
		return true;
	};

	const validateContactPerson = () => {
		const value = fields.contactPerson.value.trim();
		const words = value.split(/\s+/).filter(Boolean);
		if (words.length < 2) {
			setError(fields.contactPerson, 'contactPerson-error', 'Ingresa nombre y apellido del contacto');
			return false;
		}
		clearError(fields.contactPerson, 'contactPerson-error');
		return true;
	};

	const validateCorporateEmail = () => {
		const value = fields.corporateEmail.value.trim();
		if (!emailRegex.test(value)) {
			setError(
				fields.corporateEmail,
				'corporateEmail-error',
				'Ingresa un email corporativo válido (ejemplo: <nombre@empresa.com>)'
			);
			return false;
		}
		clearError(fields.corporateEmail, 'corporateEmail-error');
		return true;
	};

	const validatePhone = () => {
		const value = fields.phone.value.trim();
		if (!phoneRegex.test(value)) {
			setError(
				fields.phone,
				'phone-error',
				'El teléfono debe incluir código de país (ejemplo: +1 213 555 0147)'
			);
			return false;
		}
		clearError(fields.phone, 'phone-error');
		return true;
	};

	const validateWebsite = () => {
		const value = fields.website.value.trim();
		if (value && !urlRegex.test(value)) {
			setError(fields.website, 'website-error', 'Si incluyes sitio web, debe ser una URL válida');
			return false;
		}
		clearError(fields.website, 'website-error');
		return true;
	};

	const validateCountryOperation = () => {
		if (!fields.countryOperation.value) {
			setError(fields.countryOperation, 'countryOperation-error', 'Selecciona el país de operación principal');
			return false;
		}
		clearError(fields.countryOperation, 'countryOperation-error');
		return true;
	};

	const validateProductType = () => {
		if (!fields.productType.value) {
			setError(fields.productType, 'productType-error', 'Selecciona el tipo de producto que manejas');
			return false;
		}
		clearError(fields.productType, 'productType-error');
		return true;
	};

	const validateMonthlyVolume = () => {
		if (!fields.monthlyVolume.value) {
			setError(fields.monthlyVolume, 'monthlyVolume-error', 'Selecciona el volumen mensual estimado');
			return false;
		}
		clearError(fields.monthlyVolume, 'monthlyVolume-error');
		return true;
	};

	const validateServices = () => {
		const hasSelectedService = servicesCheckboxes.some((item) => item.checked);
		if (!hasSelectedService) {
			setGroupError(servicesCheckboxes, 'services-error', 'Selecciona al menos un servicio de interés');
			return false;
		}
		clearGroupError(servicesCheckboxes, 'services-error');
		return true;
	};

	const validateOther3pl = () => {
		const hasSelectedOption = other3plRadios.some((item) => item.checked);
		if (!hasSelectedOption) {
			setGroupError(other3plRadios, 'other3pl-error', 'Indica si actualmente trabajas con otro proveedor logístico');
			return false;
		}
		clearGroupError(other3plRadios, 'other3pl-error');
		return true;
	};

	const validateComments = () => {
		const remaining = 500 - fields.comments.value.length;
		if (remaining < 0) {
			setError(
				fields.comments,
				'comments-error',
				`Los comentarios no pueden exceder 500 caracteres (quedan ${remaining})`
			);
			return false;
		}
		clearError(fields.comments, 'comments-error');
		return true;
	};

	const validatePrivacyPolicy = () => {
		if (!fields.privacyPolicy.checked) {
			setGroupError([fields.privacyPolicy], 'privacyPolicy-error', 'Debes aceptar la política de privacidad para continuar');
			return false;
		}
		clearGroupError([fields.privacyPolicy], 'privacyPolicy-error');
		return true;
	};

	const validations = {
		companyName: validateCompanyName,
		contactPerson: validateContactPerson,
		corporateEmail: validateCorporateEmail,
		phone: validatePhone,
		website: validateWebsite,
		countryOperation: validateCountryOperation,
		productType: validateProductType,
		monthlyVolume: validateMonthlyVolume,
		comments: validateComments,
		privacyPolicy: validatePrivacyPolicy,
	};

	Object.entries(validations).forEach(([fieldId, validate]) => {
		const fieldElement = fields[fieldId];
		if (!fieldElement) {
			return;
		}
		const runValidation = () => {
			hideStatusMessages();
			validate();
			updateLowVolumeWarning();
			if (fieldId === 'comments') {
				updateCommentsCounter();
			}
		};
		fieldElement.addEventListener('input', runValidation);
		fieldElement.addEventListener('blur', runValidation);
	});

	servicesCheckboxes.forEach((checkbox) => {
		const runValidation = () => {
			hideStatusMessages();
			validateServices();
		};
		checkbox.addEventListener('input', runValidation);
		checkbox.addEventListener('blur', runValidation);
	});

	other3plRadios.forEach((radio) => {
		const runValidation = () => {
			hideStatusMessages();
			validateOther3pl();
		};
		radio.addEventListener('change', runValidation);
		});

	form.addEventListener('submit', (event) => {
		event.preventDefault();
		hideStatusMessages();

		const isValid = [
			validateCompanyName(),
			validateContactPerson(),
			validateCorporateEmail(),
			validatePhone(),
			validateWebsite(),
			validateCountryOperation(),
			validateProductType(),
			validateMonthlyVolume(),
			validateServices(),
			validateOther3pl(),
			validateComments(),
			validatePrivacyPolicy(),
		].every(Boolean);

		if (!isValid) {
			if (statusBox) {
				statusBox.classList.remove('hidden');
				statusBox.classList.remove('border-emerald-500/40', 'bg-emerald-400/10', 'text-emerald-200');
				statusBox.classList.add('border-red-500/40', 'bg-red-400/10', 'text-red-200');
				statusBox.textContent = 'Revisa los campos marcados para continuar con el envío.';
			}
			return;
		}

		skipResetStatusClear = true;
		form.reset();
		Object.keys(validations).forEach((fieldId) => {
			const fieldElement = fields[fieldId];
			if (fieldElement) {
				const errorId = `${fieldId}-error`;
				const errorNode = document.querySelector(`#${errorId}`);
				if (errorNode) {
					clearError(fieldElement, errorId);
				}
			}
		});
		clearGroupError(servicesCheckboxes, 'services-error');
		clearGroupError(other3plRadios, 'other3pl-error');
		clearGroupError([fields.privacyPolicy], 'privacyPolicy-error');
		updateCommentsCounter();
		updateLowVolumeWarning();

		if (statusBox) {
			statusBox.classList.remove('hidden');
			statusBox.classList.remove('border-red-500/40', 'bg-red-400/10', 'text-red-200');
			statusBox.classList.add('border-emerald-500/40', 'bg-emerald-400/10', 'text-emerald-200');
			statusBox.innerHTML =
				'<strong>¡Gracias por tu interés en TrackFlow!</strong><br><br>Hemos recibido tu solicitud. Nuestro equipo comercial revisará tu información y te contactará en las próximas 24-48 horas para agendar una llamada y conocer tus necesidades logísticas en detalle.<br><br>Si tienes alguna consulta urgente, escríbenos directamente a comercial@trackflow.com';
		}
	});

	form.addEventListener('reset', () => {
		setTimeout(() => {
			if (skipResetStatusClear) {
				skipResetStatusClear = false;
			} else {
				hideStatusMessages();
			}
			Object.keys(validations).forEach((fieldId) => {
				const fieldElement = fields[fieldId];
				if (fieldElement) {
					const errorId = `${fieldId}-error`;
					const errorNode = document.querySelector(`#${errorId}`);
					if (errorNode) {
						clearError(fieldElement, errorId);
					}
				}
			});
			clearGroupError(servicesCheckboxes, 'services-error');
			clearGroupError(other3plRadios, 'other3pl-error');
			clearGroupError([fields.privacyPolicy], 'privacyPolicy-error');
			updateCommentsCounter();
			updateLowVolumeWarning();
		}, 0);
	});

	updateCommentsCounter();
	updateLowVolumeWarning();
}
